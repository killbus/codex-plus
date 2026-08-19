use schemars::JsonSchema;
use serde::Deserialize;
use serde::Serialize;
use ts_rs::TS;

/// A completed report produced by a Shadow extension.
#[derive(Debug, Clone, Deserialize, Serialize, TS, JsonSchema, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
#[ts(rename_all = "camelCase")]
pub struct ShadowReportItem {
    pub id: String,
    pub shadow_id: String,
    pub shadow_name: String,
    pub content: String,
}
