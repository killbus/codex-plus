//! Small, host-independent Shadow Mind runtime primitives.
//!
//! The host integration owns spawning and response injection. This crate owns
//! registry validation, per-thread epochs, exactly-once scheduling, and bounded
//! report delivery.

use codex_core::NewThread;
use codex_core::StartThreadOptions;
use codex_core::ThreadManager;
use codex_core::config::Config;
use codex_core::config::Constrained;
use codex_core::config::Permissions;
use codex_extension_api::AgentSpawner;
use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_extension_api::ThreadStartInput;
use codex_extension_api::ThreadStopInput;
use codex_extension_api::TurnAbortInput;
use codex_extension_api::TurnErrorInput;
use codex_extension_api::TurnLifecycleContributor;
use codex_extension_api::TurnStartInput;
use codex_features::Feature;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::models::ContentItem;
use codex_protocol::models::PermissionProfile;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use codex_protocol::protocol::ThreadSource;
use codex_protocol::user_input::UserInput;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::hash_map::DefaultHasher;
use std::fs;
use std::future::Future;
use std::hash::Hash;
use std::hash::Hasher;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use tokio::sync::Semaphore;

pub const DEFAULT_MAX_PARALLEL: usize = 2;
pub const DEFAULT_REPORT_BATCH_WINDOW_MS: u64 = 400;
pub const MAX_TRAJECTORY_CHARS: usize = 32_000;
pub const MAX_TRAJECTORY_ITEM_CHARS: usize = 4_000;

static SHADOW_PAUSED: AtomicBool = AtomicBool::new(false);

/// Process-wide operator control used by the small `/shadow` management surface.
/// Pausing prevents new heartbeats; already-running shadows finish normally.
pub fn pause() {
    SHADOW_PAUSED.store(true, Ordering::Release);
}

pub fn resume() {
    SHADOW_PAUSED.store(false, Ordering::Release);
}

pub fn is_paused() -> bool {
    SHADOW_PAUSED.load(Ordering::Acquire)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ShadowCommand {
    List,
    Status,
    Pause,
    Resume,
}

#[derive(Debug, PartialEq, Eq)]
enum WaitOutcome<T> {
    Completed(T),
    Cancelled,
    TimedOut,
}

async fn wait_for_run<F, T>(
    run: &RunHandle,
    timeout: std::time::Duration,
    future: F,
) -> WaitOutcome<T>
where
    F: Future<Output = T>,
{
    match tokio::time::timeout(timeout, async {
        tokio::select! {
            value = future => WaitOutcome::Completed(value),
            _ = async {
                while !run.is_cancelled() {
                    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                }
            } => WaitOutcome::Cancelled,
        }
    })
    .await
    {
        Ok(outcome) => outcome,
        Err(_) => WaitOutcome::TimedOut,
    }
}

pub fn parse_shadow_command(input: &str) -> Result<ShadowCommand, &'static str> {
    match input.trim().to_ascii_lowercase().as_str() {
        "list" => Ok(ShadowCommand::List),
        "status" => Ok(ShadowCommand::Status),
        "pause" => Ok(ShadowCommand::Pause),
        "resume" => Ok(ShadowCommand::Resume),
        _ => Err("Usage: /shadow [list|status|pause|resume]"),
    }
}

pub fn is_shadow_session_source(source: &SessionSource) -> bool {
    matches!(
        source,
        SessionSource::SubAgent(SubAgentSource::Other(value)) if value.starts_with("shadow:")
    )
}

fn is_non_root_source(source: &SessionSource) -> bool {
    matches!(source, SessionSource::SubAgent(_))
}

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

#[derive(Clone, Debug)]
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
    if id.is_empty()
        || !id
            .chars()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '_' || ch == '-')
    {
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
        active_for_models: meta
            .active_for_models
            .unwrap_or_else(|| vec!["*".to_owned()]),
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
        match fs::read_to_string(&path)
            .map_err(|error| error.to_string())
            .and_then(|raw| parse_shadow_markdown(&raw, path.clone()))
        {
            Ok(shadow) if ids.insert(shadow.id.clone()) => snapshot.shadows.push(shadow),
            Ok(shadow) => snapshot.diagnostics.push(RegistryDiagnostic {
                file_path: path,
                message: format!("duplicate shadow id: {}", shadow.id),
            }),
            Err(message) => snapshot.diagnostics.push(RegistryDiagnostic {
                file_path: path,
                message,
            }),
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
        if !shadow
            .active_for_models
            .iter()
            .any(|model| model == "*" || model == main_model)
        {
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
        let mut cache = self
            .registry_cache
            .lock()
            .expect("shadow registry cache poisoned");
        let previous = cache.get(directory).cloned().unwrap_or_default();
        let invalid_paths = loaded
            .diagnostics
            .iter()
            .map(|diagnostic| diagnostic.file_path.clone())
            .collect::<BTreeSet<_>>();
        let mut snapshot = loaded;
        for shadow in previous.shadows {
            if invalid_paths.contains(&shadow.file_path)
                && !snapshot
                    .shadows
                    .iter()
                    .any(|current| current.id == shadow.id)
            {
                snapshot.shadows.push(shadow);
            }
        }
        snapshot
            .shadows
            .sort_by(|left, right| left.id.cmp(&right.id));
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
                && !is_non_root_source(input.session_source);
            let Ok(thread_id) = ThreadId::from_string(input.thread_store.level_id()) else {
                return;
            };
            input.thread_store.insert(ShadowThreadState {
                eligible: !is_non_root_source(input.session_source),
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
            if is_paused() {
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
                DEFAULT_MAX_PARALLEL.saturating_sub(state.runtime.active_runs()),
                registry
                    .shadows
                    .iter()
                    .map(|shadow| deterministic_roll(&seed, &shadow.id)),
            );
            for shadow_id in decision.selected {
                let Some(shadow) = registry
                    .shadows
                    .iter()
                    .find(|shadow| shadow.id == shadow_id)
                    .cloned()
                else {
                    continue;
                };
                let run = state.runtime.start_run_for(Some(shadow.id.clone()));
                let extension = self.clone_for_task();
                let trajectory = input.trajectory.clone();
                let expected_epoch = input.idle_epoch;
                let state = Arc::clone(&state);
                tokio::spawn(async move {
                    run_shadow(extension, state, shadow, run, trajectory, expected_epoch).await;
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
    options.session_source = Some(SessionSource::SubAgent(SubAgentSource::Other(format!(
        "shadow:{}",
        shadow.id
    ))));
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
        let completion = wait_for_run(
            &run,
            std::time::Duration::from_secs(timeout_seconds),
            async {
                loop {
                    match thread.next_event().await?.msg {
                        EventMsg::TurnComplete(event) => break Ok(event.last_agent_message),
                        _ => {}
                    }
                }
            },
        )
        .await;
        let _ = thread.shutdown_and_wait().await;
        match completion {
            WaitOutcome::Completed(result) => result,
            WaitOutcome::Cancelled => Err(CodexErr::Fatal("shadow run cancelled".to_owned())),
            WaitOutcome::TimedOut => Err(CodexErr::Fatal("shadow run timed out".to_owned())),
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
    tokio::time::sleep(std::time::Duration::from_millis(
        DEFAULT_REPORT_BATCH_WINDOW_MS,
    ))
    .await;
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
            if let ContentItem::InputText { text: part } | ContentItem::OutputText { text: part } =
                part
            {
                text.push_str(part);
            }
        }
        let lower = text.to_ascii_lowercase();
        if text.is_empty()
            || [
                "api_key",
                "apikey",
                "authorization",
                "password",
                "secret",
                "access_token",
            ]
            .iter()
            .any(|needle| lower.contains(needle))
        {
            continue;
        }
        let text = text
            .chars()
            .take(MAX_TRAJECTORY_ITEM_CHARS)
            .collect::<String>();
        let line = format!("{role}: {text}\n");
        if output.len() + line.len() > MAX_TRAJECTORY_CHARS {
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
) where
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
    fn shadow_commands_parse() {
        assert_eq!(parse_shadow_command("list"), Ok(ShadowCommand::List));
        assert_eq!(parse_shadow_command(" STATUS "), Ok(ShadowCommand::Status));
        assert_eq!(parse_shadow_command("pause"), Ok(ShadowCommand::Pause));
        assert!(parse_shadow_command("edit").is_err());
    }

    #[test]
    fn shadow_sources_cannot_recurse() {
        let source = SessionSource::SubAgent(SubAgentSource::Other("shadow:reviewer".into()));
        assert!(is_shadow_session_source(&source));
        assert!(is_non_root_source(&source));
        let guardian = SessionSource::SubAgent(SubAgentSource::Other("guardian".into()));
        assert!(!is_shadow_session_source(&guardian));
        assert!(is_non_root_source(&guardian));
    }

    #[test]
    fn heartbeat_respects_available_slots() {
        let shadow = |id: &str| ShadowDefinition {
            id: id.into(),
            name: id.into(),
            enabled: true,
            debug: false,
            activation_probability: 1.0,
            active_for_models: vec!["*".into()],
            run_with_model: None,
            thinking_level: None,
            timeout_seconds: None,
            tools: Vec::new(),
            prompt: "report".into(),
            file_path: PathBuf::from(format!("{id}.md")),
        };
        let shadows = vec![shadow("a"), shadow("b"), shadow("c")];
        let decision = decide_heartbeat(
            &shadows,
            &BTreeSet::new(),
            "model",
            2,
            std::iter::repeat(0.0),
        );
        assert_eq!(decision.selected, vec!["a", "b"]);
    }

    #[test]
    fn trajectory_redacts_secrets_and_is_bounded() {
        let history = codex_extension_api::ConversationHistory::new(vec![
            ResponseItem::Message {
                id: None,
                role: "user".into(),
                content: vec![ContentItem::InputText {
                    text: "api_key=hidden".into(),
                }],
                phase: None,
                internal_chat_message_metadata_passthrough: None,
            },
            ResponseItem::Message {
                id: None,
                role: "user".into(),
                content: vec![ContentItem::InputText {
                    text: "x".repeat(MAX_TRAJECTORY_ITEM_CHARS + 100),
                }],
                phase: None,
                internal_chat_message_metadata_passthrough: None,
            },
        ]);
        let output = sanitize_trajectory(&history);
        assert!(!output.contains("api_key"));
        assert!(output.len() <= MAX_TRAJECTORY_CHARS);
    }

    #[tokio::test]
    async fn cancellation_and_timeout_are_distinct() {
        let runtime = ThreadRuntime::default();
        let run = runtime.start_run();
        run.cancel();
        assert_eq!(
            wait_for_run(
                &run,
                std::time::Duration::from_secs(1),
                std::future::pending::<()>(),
            )
            .await,
            WaitOutcome::Cancelled
        );

        let run = runtime.start_run();
        assert_eq!(
            wait_for_run(
                &run,
                std::time::Duration::ZERO,
                std::future::pending::<()>(),
            )
            .await,
            WaitOutcome::TimedOut
        );
    }

    #[test]
    fn registry_cache_keeps_last_known_good_entry() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("reviewer.md");
        fs::write(&path, "---\nid: reviewer\n---\ncheck").expect("write");
        let extension = ShadowExtension::new((), Weak::new());
        assert_eq!(
            extension
                .load_registry(directory.path())
                .expect("load")
                .shadows
                .len(),
            1
        );

        fs::write(&path, "malformed").expect("write");
        let snapshot = extension.load_registry(directory.path()).expect("reload");
        assert_eq!(snapshot.shadows.len(), 1);
        assert_eq!(snapshot.diagnostics.len(), 1);
    }

    #[test]
    fn registry_parses_supported_frontmatter() {
        let shadow = parse_shadow_markdown(
            "---\nid: reviewer\nname: Reviewer\nenabled: false\ndebug: true\nactivation_probability: 0.5\nactive_for_models: [gpt-5]\nrun_with_model: gpt-5-mini\nthinking_level: high\ntimeout_seconds: 9\ntools: [search]\n---\ncheck",
            PathBuf::from("reviewer.md"),
        )
        .expect("parse");
        assert_eq!(
            shadow,
            ShadowDefinition {
                id: "reviewer".into(),
                name: "Reviewer".into(),
                enabled: false,
                debug: true,
                activation_probability: 0.5,
                active_for_models: vec!["gpt-5".into()],
                run_with_model: Some("gpt-5-mini".into()),
                thinking_level: Some("high".into()),
                timeout_seconds: Some(9),
                tools: vec!["search".into()],
                prompt: "check".into(),
                file_path: PathBuf::from("reviewer.md"),
            }
        );
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
        assert_eq!(
            ReportDisposition::Stale,
            runtime.accept_report(report, epoch, "turn", Some("turn"))
        );
    }

    #[test]
    fn registry_reports_duplicate_and_malformed_entries() {
        let directory = tempfile::tempdir().expect("tempdir");
        fs::write(directory.path().join("ok.md"), "---\nid: ok\n---\ncheck").expect("write");
        fs::write(
            directory.path().join("duplicate.md"),
            "---\nid: ok\n---\nagain",
        )
        .expect("write");
        fs::write(directory.path().join("bad.md"), "not markdown").expect("write");
        let snapshot = load_registry(directory.path()).expect("load");
        assert_eq!(1, snapshot.shadows.len());
        assert_eq!(2, snapshot.diagnostics.len());
    }
}
