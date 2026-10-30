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

/// How unresolved state affects instance placement. `Verified` (default) withholds
/// every placement while opaque User Data, unevaluated settings or unresolved
/// bindings remain. `SceneGraphV1` estimates placements from the stored segment
/// tree, modelling matrices and references anyway; results are labeled estimates
/// (`hsf.placement_estimated`) and strict mode rejects the policy.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlacementPolicy {
    #[default]
    Verified,
    SceneGraphV1,
}
impl PlacementPolicy {
    pub(crate) fn backend(self) -> hsf_core::PlacementPolicy {
        match self {
            Self::Verified => hsf_core::PlacementPolicy::Verified,
            Self::SceneGraphV1 => hsf_core::PlacementPolicy::BestEffort,
        }
    }
}

/// Caller-provided import namespace and placement policy. External
/// attributes/geometry are not loaded.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SceneContext {
    pub import_root: Option<String>,
    pub placement: PlacementPolicy,
}
