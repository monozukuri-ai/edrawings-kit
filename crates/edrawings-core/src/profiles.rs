use crate::UserDataPolicy;
use serde::{Deserialize, Serialize};

/// Empirical wire framing is opt-in and never accepted by strict parsing.
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ImagePolicy {
    #[default]
    Disabled,
    Edrawings1910U32V1,
}
impl ImagePolicy {
    pub(crate) fn backend(self) -> hsf_core::ImageProfile {
        match self {
            Self::Disabled => hsf_core::ImageProfile::Disabled,
            Self::Edrawings1910U32V1 => hsf_core::ImageProfile::U32RgbaJpegV1,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct HsfProfiles {
    pub user_data: UserDataPolicy,
    pub image: ImagePolicy,
}

/// Caller-provided import namespace. External attributes/geometry are not loaded.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SceneContext {
    pub import_root: Option<String>,
}
