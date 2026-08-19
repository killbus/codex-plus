use super::input_queue::TurnInput;
use super::session::Session;
use super::turn_context::TurnContext;
use crate::codex_thread::TryStartTurnIfIdleError;
use crate::codex_thread::TryStartTurnIfIdleRejectionReason;
use crate::state::ActiveTurn;
use crate::state::TurnState;
use crate::tasks::RegularTask;
use codex_extension_api::AutomaticTurnOrigin;
use codex_protocol::config_types::ModeKind;
use codex_protocol::items::TurnItem;
use codex_protocol::models::ResponseItem;
use std::sync::Arc;
use std::sync::atomic::Ordering;

impl Session {
    /// Returns the input if there is no active turn to inject into.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active turn checks and turn state updates must remain atomic"
    )]
    pub async fn inject_if_running(
        &self,
        input: Vec<ResponseItem>,
    ) -> Result<(), Vec<ResponseItem>> {
        let mut active = self.active_turn.lock().await;
        match active.as_mut() {
            Some(active_turn) => {
                self.input_queue
                    .extend_pending_input_and_accept_mailbox_delivery_for_turn_state(
                        active_turn.turn_state.as_ref(),
                        input.into_iter().map(TurnInput::ResponseItem).collect(),
                    )
                    .await;
                Ok(())
            }
            None => Err(input),
        }
    }

    /// Injects only if the expected turn is active at the enqueue point.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active turn checks and turn state updates must remain atomic"
    )]
    pub async fn inject_if_running_for_turn(
        &self,
        expected_turn_id: &str,
        input: Vec<ResponseItem>,
    ) -> Result<(), Vec<ResponseItem>> {
        let mut active = self.active_turn.lock().await;
        let Some(active_turn) = active.as_mut() else {
            return Err(input);
        };
        if active_turn
            .task
            .as_ref()
            .map(|task| task.turn_context.sub_id.as_str())
            != Some(expected_turn_id)
        {
            return Err(input);
        }
        self.input_queue
            .extend_pending_input_and_accept_mailbox_delivery_for_turn_state(
                active_turn.turn_state.as_ref(),
                input.into_iter().map(TurnInput::ResponseItem).collect(),
            )
            .await;
        Ok(())
    }

    /// Starts a regular turn with the provided items only if automatic idle work
    /// is allowed for the current session state.
    ///
    /// This is the shared gate for extension-initiated idle work. It refuses to
    /// start a turn when user/client-triggered work is queued, any task is still
    /// active, or the session is currently in Plan mode. Active Review tasks are
    /// covered by the active-task check because Review turns are not steerable.
    pub(crate) async fn try_start_turn_if_idle(
        self: &Arc<Self>,
        input: Vec<ResponseItem>,
    ) -> Result<(), TryStartTurnIfIdleError> {
        self.try_start_turn_if_idle_inner(
            /*expected_idle_epoch*/ None,
            AutomaticTurnOrigin::Unspecified,
            Vec::new(),
            input,
        )
        .await
    }

    pub(crate) async fn try_start_turn_if_idle_for_epoch(
        self: &Arc<Self>,
        expected_idle_epoch: u64,
        input: Vec<ResponseItem>,
    ) -> Result<(), TryStartTurnIfIdleError> {
        self.try_start_turn_if_idle_inner(
            Some(expected_idle_epoch),
            AutomaticTurnOrigin::Unspecified,
            Vec::new(),
            input,
        )
        .await
    }

    pub(crate) async fn try_start_turn_if_idle_for_epoch_with_origin(
        self: &Arc<Self>,
        expected_idle_epoch: u64,
        automatic_turn_origin: AutomaticTurnOrigin,
        display_items: Vec<TurnItem>,
        input: Vec<ResponseItem>,
    ) -> Result<(), TryStartTurnIfIdleError> {
        self.try_start_turn_if_idle_inner(
            Some(expected_idle_epoch),
            automatic_turn_origin,
            display_items,
            input,
        )
        .await
    }

    async fn try_start_turn_if_idle_inner(
        self: &Arc<Self>,
        expected_idle_epoch: Option<u64>,
        automatic_turn_origin: AutomaticTurnOrigin,
        display_items: Vec<TurnItem>,
        input: Vec<ResponseItem>,
    ) -> Result<(), TryStartTurnIfIdleError> {
        if input.is_empty() {
            return Ok(());
        }
        if self.input_queue.has_trigger_turn_mailbox_items().await {
            return Err(TryStartTurnIfIdleError::new(
                TryStartTurnIfIdleRejectionReason::PendingTriggerTurn,
                input,
            ));
        }
        if self.collaboration_mode().await.mode == ModeKind::Plan {
            return Err(TryStartTurnIfIdleError::new(
                TryStartTurnIfIdleRejectionReason::PlanMode,
                input,
            ));
        }

        let turn_state = {
            let mut active_turn = self.active_turn.lock().await;
            if expected_idle_epoch
                .is_some_and(|expected| self.idle_epoch.load(Ordering::Acquire) != expected)
            {
                return Err(TryStartTurnIfIdleError::new(
                    TryStartTurnIfIdleRejectionReason::StaleIdleEpoch,
                    input,
                ));
            }
            if active_turn.is_some() {
                return Err(TryStartTurnIfIdleError::new(
                    TryStartTurnIfIdleRejectionReason::Busy,
                    input,
                ));
            }
            let active_turn = active_turn.get_or_insert_with(ActiveTurn::default);
            Arc::clone(&active_turn.turn_state)
        };

        if self.input_queue.has_trigger_turn_mailbox_items().await {
            self.clear_reserved_idle_turn(&turn_state).await;
            self.maybe_start_turn_for_pending_work().await;
            return Err(TryStartTurnIfIdleError::new(
                TryStartTurnIfIdleRejectionReason::PendingTriggerTurn,
                input,
            ));
        }

        let turn_context = self
            .new_default_turn_with_sub_id_and_origin(
                uuid::Uuid::new_v4().to_string(),
                automatic_turn_origin,
            )
            .await;
        if turn_context.mode == ModeKind::Plan {
            self.clear_reserved_idle_turn(&turn_state).await;
            self.maybe_start_turn_for_pending_work().await;
            return Err(TryStartTurnIfIdleError::new(
                TryStartTurnIfIdleRejectionReason::PlanMode,
                input,
            ));
        }
        self.maybe_emit_model_warnings_for_turn(turn_context.as_ref())
            .await;
        if self.input_queue.has_trigger_turn_mailbox_items().await {
            self.clear_reserved_idle_turn(&turn_state).await;
            self.maybe_start_turn_for_pending_work().await;
            return Err(TryStartTurnIfIdleError::new(
                TryStartTurnIfIdleRejectionReason::PendingTriggerTurn,
                input,
            ));
        }
        let still_reserved = {
            let active_turn = self.active_turn.lock().await;
            active_turn.as_ref().is_some_and(|active_turn| {
                active_turn.task.is_none() && Arc::ptr_eq(&active_turn.turn_state, &turn_state)
            })
        };
        if !still_reserved {
            self.clear_reserved_idle_turn(&turn_state).await;
            return Err(TryStartTurnIfIdleError::new(
                TryStartTurnIfIdleRejectionReason::Busy,
                input,
            ));
        }

        let mut pending_input = Vec::with_capacity(display_items.len() + input.len());
        pending_input.extend(
            display_items
                .into_iter()
                .map(|item| TurnInput::DisplayItem(Box::new(item))),
        );
        pending_input.extend(input.into_iter().map(TurnInput::ResponseItem));
        self.input_queue
            .extend_pending_input_for_turn_state(turn_state.as_ref(), pending_input)
            .await;
        self.start_task(turn_context, Vec::new(), RegularTask::new())
            .await;
        Ok(())
    }

    async fn clear_reserved_idle_turn(&self, turn_state: &Arc<tokio::sync::Mutex<TurnState>>) {
        let mut active_turn_guard = self.active_turn.lock().await;
        if let Some(active_turn) = active_turn_guard.as_ref()
            && active_turn.task.is_none()
            && Arc::ptr_eq(&active_turn.turn_state, turn_state)
        {
            *active_turn_guard = None;
        }
    }

    /// Injects items into active work, or records them without starting a turn.
    pub(crate) async fn inject_no_new_turn(
        &self,
        items: Vec<ResponseItem>,
        current_turn_context: Option<&TurnContext>,
    ) {
        let Err(items) = self.inject_if_running(items).await else {
            return;
        };
        let default_turn_context;
        let turn_context = match current_turn_context {
            Some(turn_context) => turn_context,
            None => {
                default_turn_context = self.new_default_turn().await;
                default_turn_context.as_ref()
            }
        };
        self.record_conversation_items(turn_context, &items).await;
    }
}
