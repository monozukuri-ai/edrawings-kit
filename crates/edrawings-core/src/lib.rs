//! eDrawings containers and bounded HSF syntax. Bounded generic 3D scenes.
mod components;
mod configurations;
mod container;
mod document;
mod drawing;
mod drawing_plane;
mod error;
mod hsf_adapter;
mod limits;
mod metadata;
mod model;
mod probe;
mod resources;
mod sheets;
mod user_data;
mod user_options;
pub use drawing::*;
pub use user_data::UserDataPolicy;
mod profiles;
pub use profiles::{HsfProfiles, ImagePolicy, SceneContext};
mod scene_adapter;
pub use scene_adapter::*;

pub use document::*;
pub use error::Error;
pub use hsf_adapter::{HsfDocument, HsfMode};
pub use limits::Limits;
pub use model::*;
pub use probe::probe_bytes;
use sha2::{Digest, Sha256};
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub fn sha256(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}
pub fn build_info() -> BuildInfo {
    BuildInfo {
        version: VERSION.into(),
        hsf_version: hsf_core::VERSION.into(),
        contract_version: hsf_core::CONTRACT_VERSION,
        capabilities: [
            "raw_hsf",
            "zip_store",
            "zip_deflate",
            "edrawings_prefix_92",
            "hsf_header",
            "xml_structure",
            "hsf_syntax_prefix",
            "hsf_internal_zlib",
            "scene",
            "drawing_primitives",
            "segment_user_options",
            "drawing_user_option_assignments",
            "stored_component_tree",
            "stored_component_part_transforms",
            "stored_multiple_configurations",
            "stored_sheet_view_inventory",
            "bounded_drawing_plane_units",
            "mesh_buffers",
            "experimental_edrawings_first_be_v2",
            "experimental_edrawings_be_envelope_v1",
            "named_views",
            "world_handedness",
            "opaque_user_data_inventory",
        ]
        .map(String::from)
        .to_vec(),
        hsf_source_sha256: hsf_core::SOURCE_SHA256.into(),
        hsf_syntax_versions: hsf_core::capabilities().syntax_versions,
        hsf_syntax_opcodes: hsf_core::capabilities().syntax_opcodes,
        hsf_scene_features: hsf_core::capabilities().scene_features,
    }
}
