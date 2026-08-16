//! Small, host-independent Shadow Mind runtime primitives.
//!
//! The host integration owns spawning and response injection. This crate owns
//! registry validation, per-thread epochs, exactly-once scheduling, and bounded
//! report delivery.

use serde::Deserialize;
use codex_core::config::Config;
use codex_core::config::Constrained;
use codex_core::config::Permissions;
use codex_core::NewThread;
use codex_core::StartThreadOptions;
use codex_core::ThreadManager;
use codex_extension_api::AgentSpawner;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::ThreadStopInput;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::TurnAbortInput;
use codex_extension_api::TurnErrorInput;
use codex_extension_api::TurnLifecycleContributor;
use codex_extension_api::TurnStartInput;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use codex_protocol::ThreadId;
use codex_protocol::protocol::ThreadSource;
use codex_protocol::user_input::UserInput;
use codex_protocol::error::CodexErr;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::models::PermissionProfile;
use codex_features::Feature;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, Weak};
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use tokio::sync::Semaphore;

pub const DEFAULT_MAX_PARALLEL: usize = 2;
pub const DEFAULT_REPORT_BATCH_WINDOW_MS: u64 = 400;

#[derive(Clone, Debug, PartialEq)]
pub struct ShadowDefinition {
    pub id: String,
    pub name: String,
    pub enabled: bool,
    pub debug: bool,
    pub activation_probability: f64,
    pub active_for_models: Vec<String>,
    pub run_with_model: Option<String>,
    pub thinking_level: Option<String>,
    pub timeout_seconds: Option<u64>,
    pub tools: Vec<String>,
    pub prompt: String,
    pub file_path: PathBuf,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RegistryDiagnostic {
    pub file_path: PathBuf,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegistrySnapshot {
    pub shadows: Vec<ShadowDefinition>,
    pub diagnostics: Vec<RegistryDiagnostic>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShadowReport {
    pub shadow_id: String,
    pub shadow_name: String,
    pub content: String,
    pub epoch: u64,
    pub run_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReportDisposition {
    Accepted,
    Stale,
    WrongTurn,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HeartbeatDecision {
    pub candidates: Vec<String>,
    pub selected: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RunHandle {
    pub run_id: String,
    pub epoch: u64,
    shadow_id: Option<String>,
    cancelled: Arc<AtomicBool>,
}

impl RunHandle {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }
}

#[derive(Default)]
pub struct ThreadRuntime {
    epoch: AtomicU64,
    next_run_id: AtomicU64,
    scheduled_turn: Mutex<Option<String>>,
    runs: Mutex<BTreeMap<String, RunHandle>>,
    reports: Mutex<Vec<ShadowReport>>,
    delivery_lock: tokio::sync::Mutex<()>,
}

impl ThreadRuntime {
    pub fn epoch(&self) -> u64 {
        self.epoch.load(Ordering::Acquire)
    }

    /// Starts a new user epoch and cancels every old shadow run.
    pub fn begin_user_input(&self) -> u64 {
        let epoch = self.epoch.fetch_add(1, Ordering::AcqRel) + 1;
        for run in self.runs.lock().expect("shadow run lock poisoned").values() {
            run.cancel();
        }
        self.reports.lock().expect("report lock poisoned").clear();
        epoch
    }

    pub fn cancel_runs(&self) {
        for run in self.runs.lock().expect("shadow run lock poisoned").values() {
            run.cancel();
        }
    }

    /// The only lifecycle edge allowed to schedule a heartbeat.
    pub fn schedule_once(&self, completed_turn_id: &str) -> bool {
        let mut scheduled = self.scheduled_turn.lock().expect("schedule lock poisoned");
        if scheduled.as_deref() == Some(completed_turn_id) {
            return false;
        }
        *scheduled = Some(completed_turn_id.to_owned());
        true
    }

    pub fn start_run(&self) -> RunHandle {
        self.start_run_for(None)
    }

    fn start_run_for(&self, shadow_id: Option<String>) -> RunHandle {
        let run_id = self.next_run_id.fetch_add(1, Ordering::Relaxed).to_string();
        let run = RunHandle {
            run_id: run_id.clone(),
            epoch: self.epoch(),
            shadow_id,
            cancelled: Arc::new(AtomicBool::new(false)),
        };
        self.runs
            .lock()
            .expect("shadow run lock poisoned")
            .insert(run_id, run.clone());
        run
    }

    pub fn finish_run(&self, run_id: &str) {
        self.runs
            .lock()
            .expect("shadow run lock poisoned")
            .remove(run_id);
    }

    pub fn active_runs(&self) -> usize {
        self.runs.lock().expect("shadow run lock poisoned").len()
    }

    /// Atomically checks epoch and expected active turn before queueing a report.
    pub fn accept_report(
        &self,
        report: ShadowReport,
        expected_epoch: u64,
        expected_turn_id: &str,
        active_turn_id: Option<&str>,
    ) -> ReportDisposition {
        if report.epoch != self.epoch() || report.epoch != expected_epoch {
            return ReportDisposition::Stale;
        }
        if active_turn_id != Some(expected_turn_id) {
            return ReportDisposition::WrongTurn;
        }
        self.reports
            .lock()
            .expect("report lock poisoned")
            .push(report);
        ReportDisposition::Accepted
    }

    pub fn take_reports(&self) -> Vec<ShadowReport> {
        std::mem::take(&mut *self.reports.lock().expect("report lock poisoned"))
    }

    fn active_run_ids(&self) -> BTreeSet<String> {
        self.runs
            .lock()
            .expect("shadow run lock poisoned")
            .values()
            .filter_map(|run| run.shadow_id.clone())
            .collect()
    }

    fn accept_idle_report(&self, report: ShadowReport, expected_epoch: u64) -> bool {
        if report.epoch != expected_epoch || report.epoch != self.epoch() {
            return false;
        }
        self.reports
            .lock()
            .expect("report lock poisoned")
            .push(report);
        true
    }

    fn take_reports_for_delivery(&self) -> Vec<ShadowReport> {
        std::mem::take(&mut *self.reports.lock().expect("report lock poisoned"))
    }

}

#[derive(Debug, Deserialize)]
struct Frontmatter {
    id: Option<String>,
    name: Option<String>,
    enabled: Option<bool>,
    debug: Option<bool>,
    activation_probability: Option<f64>,
    active_for_models: Option<Vec<String>>,
    run_with_model: Option<String>,
    thinking_level: Option<String>,
    timeout_seconds: Option<u64>,
    tools: Option<Vec<String>>,
}

pub fn parse_shadow_markdown(source: &str, file_path: PathBuf) -> Result<ShadowDefinition, String> {
    let mut sections = source.splitn(3, "---");
    let first = sections.next().unwrap_or_default();
    let yaml = sections.next().ok_or("missing YAML frontmatter")?;
    let prompt = sections.next().ok_or("missing shadow prompt body")?.trim();
    if !first.trim().is_empty() || prompt.is_empty() {
        return Err("shadow prompt body is empty or frontmatter is malformed".to_owned());
    }
    let meta: Frontmatter = serde_yaml::from_str(yaml).map_err(|error| error.to_string())?;
    let fallback_id = file_path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_owned();
    let id = meta.id.unwrap_or(fallback_id);
    if id.is_empty() || !id.chars().enumerate().all(|(index, ch)| {
        ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '_' || ch == '-' || (index > 0 && ch == '-')
    }) {
        return Err("id must contain only lowercase letters, digits, '_' or '-'".to_owned());
    }
    let probability = meta.activation_probability.unwrap_or(0.3);
    if !probability.is_finite() || !(0.0..=1.0).contains(&probability) {
        return Err("activation_probability must be between 0 and 1".to_owned());
    }
    Ok(ShadowDefinition {
        name: meta.name.unwrap_or_else(|| id.clone()),
        id,
        enabled: meta.enabled.unwrap_or(true),
        debug: meta.debug.unwrap_or(false),
        activation_probability: probability,
        active_for_models: meta.active_for_models.unwrap_or_else(|| vec!["*".to_owned()]),
        run_with_model: meta.run_with_model,
        thinking_level: meta.thinking_level,
        timeout_seconds: meta.timeout_seconds,
        tools: meta.tools.unwrap_or_default(),
        prompt: prompt.to_owned(),
        file_path,
    })
}

pub fn load_registry(directory: &Path) -> std::io::Result<RegistrySnapshot> {
    let mut snapshot = RegistrySnapshot::default();
    if !directory.exists() {
        return Ok(snapshot);
    }
    let mut paths = fs::read_dir(directory)?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.extension().and_then(|ext| ext.to_str()) == Some("md"))
        .collect::<Vec<_>>();
    paths.sort();
    let mut ids = BTreeSet::new();
    for path in paths {
        match fs::read_to_string(&path).map_err(|error| error.to_string()).and_then(|raw| parse_shadow_markdown(&raw, path.clone())) {
            Ok(shadow) if ids.insert(shadow.id.clone()) => snapshot.shadows.push(shadow),
            Ok(shadow) => snapshot.diagnostics.push(RegistryDiagnostic {
                file_path: path,
                message: format!("duplicate shadow id: {}", shadow.id),
            }),
            Err(message) => snapshot.diagnostics.push(RegistryDiagnostic { file_path: path, message }),
        }
    }
    Ok(snapshot)
}

pub fn decide_heartbeat(
    shadows: &[ShadowDefinition],
    active_ids: &BTreeSet<String>,
    main_model: &str,
    available_slots: usize,
    random_rolls: impl Iterator<Item = f64>,
) -> HeartbeatDecision {
    let mut rolls = random_rolls;
    let mut decision = HeartbeatDecision::default();
    for shadow in shadows {
        if !shadow.enabled || active_ids.contains(&shadow.id) {
            continue;
        }
        if !shadow.active_for_models.iter().any(|model| model == "*" || model == main_model) {
            continue;
        }
        decision.candidates.push(shadow.id.clone());
        if rolls.next().unwrap_or(1.0) < shadow.activation_probability
            && decision.selected.len() < available_slots
        {
            decision.selected.push(shadow.id.clone());
        }
    }
    decision
}

struct ShadowThreadState {
    eligible: bool,
    enabled: AtomicBool,
    thread_id: ThreadId,
    config: Config,
    registry_dir: PathBuf,
    runtime: Arc<ThreadRuntime>,
}

/// Lifecycle-backed shadow scheduler. The host owns the spawn capability and
/// the extension owns only registry parsing, cancellation, and report policy.
pub struct ShadowExtension<S> {
    agent_spawner: Arc<S>,
    thread_manager: Weak<ThreadManager>,
    slots: Arc<Semaphore>,
    registry_cache: Mutex<BTreeMap<PathBuf, RegistrySnapshot>>,
}

impl<S> ShadowExtension<S> {
    pub fn new(agent_spawner: S, thread_manager: Weak<ThreadManager>) -> Self {
        Self {
            agent_spawner: Arc::new(agent_spawner),
            thread_manager,
            slots: Arc::new(Semaphore::new(DEFAULT_MAX_PARALLEL)),
            registry_cache: Mutex::new(BTreeMap::new()),
        }
    }

    fn load_registry(&self, directory: &Path) -> std::io::Result<RegistrySnapshot> {
        let loaded = load_registry(directory)?;
        let mut cache = self.registry_cache.lock().expect("shadow registry cache poisoned");
        let previous = cache.get(directory).cloned().unwrap_or_default();
        let invalid_paths = loaded
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.file_path.clone())
            .collect::<BTreeSet<_>>();
        let mut snapshot = loaded;
        for shadow in previous.shadows {
            if invalid_paths.contains(&shadow.file_path)
                && !snapshot.shadows.iter().any(|current| current.id == shadow.id)
            {
                snapshot.shadows.push(shadow);
            }
        }
        snapshot.shadows.sort_by(|left, right| left.id.cmp(&right.id));
        cache.insert(directory.to_owned(), snapshot.clone());
        Ok(snapshot)
    }
}

impl<S> ThreadLifecycleContributor<Config> for ShadowExtension<S>
where
    S: AgentSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr>
        + Send
        + Sync
        + 'static,
{
    fn on_thread_start<'a>(
        &'a self,
        input: ThreadStartInput<'a, Config>,
    ) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let enabled = input.config.features.enabled(Feature::Shadow)
                && !matches!(input.session_source, SessionSource::SubAgent(_));
            let Ok(thread_id) = ThreadId::from_string(input.thread_store.level_id()) else {
                return;
            };
            input.thread_store.insert(ShadowThreadState {
                eligible: !matches!(input.session_source, SessionSource::SubAgent(_)),
                enabled: AtomicBool::new(enabled),
                thread_id,
                config: input.config.clone(),
                registry_dir: input.config.codex_home.as_path().join("shadow-minds"),
                runtime: Arc::new(ThreadRuntime::default()),
            });
        })
    }

    fn on_thread_idle<'a>(&'a self, input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            let Some(state) = input.thread_store.get::<ShadowThreadState>() else {
                return;
            };
            if !state.enabled.load(Ordering::Acquire) {
                return;
            }
            let Some(completed_turn_id) = input.completed_turn_id else {
                return;
            };
            if !state.runtime.schedule_once(completed_turn_id) {
                return;
            }
            let registry = match self.load_registry(&state.registry_dir) {
                Ok(registry) => registry,
                Err(error) => {
                    tracing::warn!(path = %state.registry_dir.display(), %error, "failed to load shadow registry");
                    return;
                }
            };
            for diagnostic in &registry.diagnostics {
                tracing::warn!(path = %diagnostic.file_path.display(), message = %diagnostic.message, "invalid shadow registry entry");
            }
            let main_model = state.config.model.as_deref().unwrap_or_default();
            let seed = format!("{}:{completed_turn_id}", state.thread_id);
            let decision = decide_heartbeat(
                &registry.shadows,
                &state.runtime.active_run_ids(),
                main_model,
                DEFAULT_MAX_PARALLEL,
                registry.shadows.iter().map(|shadow| {
                    deterministic_roll(&seed, &shadow.id)
                }),
            );
            for shadow_id in decision.selected {
                let Some(shadow) = registry.shadows.iter().find(|shadow| shadow.id == shadow_id).cloned() else {
                    continue;
                };
                let run = state.runtime.start_run_for(Some(shadow.id.clone()));
                let extension = self.clone_for_task();
                let trajectory = input.trajectory.clone();
                let expected_epoch = input.idle_epoch;
                let state = Arc::clone(&state);
                tokio::spawn(async move {
                    run_shadow(
                        extension,
                        state,
                        shadow,
                        run,
                        trajectory,
                        expected_epoch,
                    )
                    .await;
                });
            }
        })
    }

    fn on_thread_stop<'a>(&'a self, input: ThreadStopInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(state) = input.thread_store.get::<ShadowThreadState>() {
                state.runtime.cancel_runs();
            }
        })
    }
}

impl<S> TurnLifecycleContributor for ShadowExtension<S>
where
    S: AgentSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr>
        + Send
        + Sync
        + 'static,
{
    fn on_turn_start<'a>(&'a self, input: TurnStartInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(state) = input.thread_store.get::<ShadowThreadState>() {
                state.runtime.begin_user_input();
            }
        })
    }

    fn on_turn_abort<'a>(&'a self, input: TurnAbortInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(state) = input.thread_store.get::<ShadowThreadState>() {
                state.runtime.cancel_runs();
            }
        })
    }

    fn on_turn_error<'a>(&'a self, input: TurnErrorInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if let Some(state) = input.thread_store.get::<ShadowThreadState>() {
                state.runtime.cancel_runs();
            }
        })
    }
}

impl<S> codex_extension_api::ConfigContributor<Config> for ShadowExtension<S>
where
    S: AgentSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr>
        + Send
        + Sync
        + 'static,
{
    fn on_config_changed(
        &self,
        _session_store: &codex_extension_api::ExtensionData,
        thread_store: &codex_extension_api::ExtensionData,
        _previous_config: &Config,
        new_config: &Config,
    ) {
        if let Some(state) = thread_store.get::<ShadowThreadState>() {
            state.enabled.store(
                state.eligible && new_config.features.enabled(Feature::Shadow),
                Ordering::Release,
            );
        }
    }
}

impl<S> ShadowExtension<S>
where
    S: AgentSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr>
        + Send
        + Sync
        + 'static,
{
    fn clone_for_task(&self) -> ShadowTaskHost<S> {
        ShadowTaskHost {
            agent_spawner: Arc::clone(&self.agent_spawner),
            thread_manager: self.thread_manager.clone(),
            slots: Arc::clone(&self.slots),
        }
    }
}

struct ShadowTaskHost<S> {
    agent_spawner: Arc<S>,
    thread_manager: Weak<ThreadManager>,
    slots: Arc<Semaphore>,
}

async fn run_shadow<S>(
    host: ShadowTaskHost<S>,
    state: Arc<ShadowThreadState>,
    shadow: ShadowDefinition,
    run: RunHandle,
    trajectory: codex_extension_api::ConversationHistory,
    expected_epoch: u64,
) where
    S: AgentSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr>
        + Send
        + Sync
        + 'static,
{
    let permit = match Arc::clone(&host.slots).acquire_owned().await {
        Ok(permit) => permit,
        Err(_) => {
            state.runtime.finish_run(&run.run_id);
            return;
        }
    };
    if run.is_cancelled() {
        state.runtime.finish_run(&run.run_id);
        return;
    }

    let mut config = state.config.clone();
    if let Some(model) = shadow.run_with_model.clone() {
        config.model = Some(model);
    }
    config.permissions = Permissions::from_approval_and_profile(
        Constrained::allow_any(AskForApproval::Never),
        Constrained::allow_any(PermissionProfile::read_only()),
    )
    .expect("built-in read-only shadow permissions must be valid");
    let mut options = StartThreadOptions::new(config);
    options.session_source = Some(SessionSource::SubAgent(SubAgentSource::Other(
        format!("shadow:{}", shadow.id),
    )));
    options.thread_source = Some(ThreadSource::Feature("shadow".to_owned()));
    let prompt = format_shadow_prompt(&shadow, &trajectory);
    let result = async {
        let NewThread { thread, .. } = host
            .agent_spawner
            .spawn_subagent(state.thread_id, options)
            .await?;
        if run.is_cancelled() {
            let _ = thread.shutdown_and_wait().await;
            return Ok::<Option<String>, CodexErr>(None);
        }
        thread
            .submit_with_trace(
                Op::UserInput {
                    items: vec![UserInput::Text {
                        text: prompt,
                        text_elements: Vec::new(),
                    }],
                    final_output_json_schema: None,
                    responsesapi_client_metadata: None,
                    additional_context: Default::default(),
                    thread_settings: Default::default(),
                },
                None,
            )
            .await?;
        let timeout_seconds = shadow.timeout_seconds.unwrap_or(120);
        let completion = tokio::time::timeout(
            std::time::Duration::from_secs(timeout_seconds),
            async {
                tokio::select! {
                    result = async {
                        loop {
                            match thread.next_event().await?.msg {
                                EventMsg::TurnComplete(event) => break Ok(event.last_agent_message),
                                _ => {}
                            }
                        }
                    } => result,
                    _ = async {
                        while !run.is_cancelled() {
                            tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                        }
                    } => Err(CodexErr::Fatal("shadow run cancelled".to_owned())),
                }
            }
        )
        .await;
        let _ = thread.shutdown_and_wait().await;
        match completion {
            Ok(result) => result,
            Err(_) => Err(CodexErr::Fatal("shadow run timed out".to_owned())),
        }
    }
    .await;
    drop(permit);

    let Ok(Some(content)) = result else {
        state.runtime.finish_run(&run.run_id);
        return;
    };
    if run.is_cancelled() {
        state.runtime.finish_run(&run.run_id);
        return;
    }
    let report = ShadowReport {
        shadow_id: shadow.id.clone(),
        shadow_name: shadow.name.clone(),
        content,
        epoch: expected_epoch,
        run_id: run.run_id.clone(),
    };
    if !state.runtime.accept_idle_report(report, expected_epoch) {
        state.runtime.finish_run(&run.run_id);
        return;
    }
    tokio::time::sleep(std::time::Duration::from_millis(DEFAULT_REPORT_BATCH_WINDOW_MS)).await;
    if run.is_cancelled() {
        state.runtime.finish_run(&run.run_id);
        return;
    }
    let _delivery = state.runtime.delivery_lock.lock().await;
    let reports = state.runtime.take_reports_for_delivery();
    if reports.is_empty() {
        state.runtime.finish_run(&run.run_id);
        return;
    }
    let items = reports
        .into_iter()
        .map(|report| shadow_report_item(&report))
        .collect::<Vec<_>>();
    if let Some(manager) = host.thread_manager.upgrade()
        && let Ok(parent) = manager.get_thread(state.thread_id).await
        && let Err(error) = parent
            .try_start_turn_if_idle_for_epoch(expected_epoch, items)
            .await
    {
        tracing::debug!(reason = ?error.reason(), "shadow report dropped at idle boundary");
    }
    state.runtime.finish_run(&run.run_id);
}

fn deterministic_roll(seed: &str, shadow_id: &str) -> f64 {
    let mut hasher = DefaultHasher::new();
    seed.hash(&mut hasher);
    shadow_id.hash(&mut hasher);
    (hasher.finish() as f64) / (u64::MAX as f64)
}

fn format_shadow_prompt(
    shadow: &ShadowDefinition,
    history: &codex_extension_api::ConversationHistory,
) -> String {
    let trajectory = sanitize_trajectory(history);
    format!(
        "{}\n\nReturn one concise report for the main thread. Do not call tools.\n\nMain-thread context:\n{}",
        shadow.prompt, trajectory
    )
}

fn sanitize_trajectory(history: &codex_extension_api::ConversationHistory) -> String {
    let mut output = String::new();
    for item in history.items().iter().rev() {
        let ResponseItem::Message { role, content, .. } = item else {
            continue;
        };
        if !matches!(role.as_str(), "developer" | "user" | "assistant") {
            continue;
        }
        let mut text = String::new();
        for part in content {
            if let ContentItem::InputText { text: part } | ContentItem::OutputText { text: part } = part {
                text.push_str(part);
            }
        }
        if text.is_empty() || text.to_ascii_lowercase().contains("api_key") || text.to_ascii_lowercase().contains("authorization") {
            continue;
        }
        let text = text.chars().take(4_000).collect::<String>();
        let line = format!("{role}: {text}\n");
        if output.len() + line.len() > 32_000 {
            break;
        }
        output.insert_str(0, &line);
    }
    output
}

fn shadow_report_item(report: &ShadowReport) -> ResponseItem {
    ResponseItem::Message {
        id: None,
        role: "user".to_owned(),
        content: vec![ContentItem::InputText {
            text: format!("[shadow:{}] {}", report.shadow_name, report.content),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

/// Installs the feature-gated shadow lifecycle contributors.
pub fn install<S>(
    registry: &mut ExtensionRegistryBuilder<Config>,
    agent_spawner: S,
    thread_manager: Weak<ThreadManager>,
)
where
    S: AgentSpawner<StartThreadOptions, Spawned = NewThread, Error = CodexErr>
        + Send
        + Sync
        + 'static,
{
    let extension = Arc::new(ShadowExtension::new(agent_spawner, thread_manager));
    registry.thread_lifecycle_contributor(extension.clone());
    registry.turn_lifecycle_contributor(extension.clone());
    registry.config_contributor(extension);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duplicate_idle_is_suppressed() {
        let runtime = ThreadRuntime::default();
        assert!(runtime.schedule_once("turn-1"));
        assert!(!runtime.schedule_once("turn-1"));
        assert!(runtime.schedule_once("turn-2"));
    }

    #[test]
    fn old_epoch_report_is_rejected() {
        let runtime = ThreadRuntime::default();
        let epoch = runtime.epoch();
        runtime.begin_user_input();
        let report = ShadowReport {
            shadow_id: "reviewer".to_owned(),
            shadow_name: "Reviewer".to_owned(),
            content: "late".to_owned(),
            epoch,
            run_id: "1".to_owned(),
        };
        assert_eq!(ReportDisposition::Stale, runtime.accept_report(report, epoch, "turn", Some("turn")));
    }

    #[test]
    fn registry_reports_duplicate_and_malformed_entries() {
        let directory = tempfile::tempdir().expect("tempdir");
        fs::write(directory.path().join("ok.md"), "---\nid: ok\n---\ncheck").expect("write");
        fs::write(directory.path().join("duplicate.md"), "---\nid: ok\n---\nagain").expect("write");
        fs::write(directory.path().join("bad.md"), "not markdown").expect("write");
        let snapshot = load_registry(directory.path()).expect("load");
        assert_eq!(1, snapshot.shadows.len());
        assert_eq!(2, snapshot.diagnostics.len());
    }
}
