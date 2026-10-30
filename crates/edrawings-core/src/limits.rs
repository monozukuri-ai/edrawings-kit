use crate::Error;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Limits {
    pub max_hsf_image_pixels: u64,
    pub max_hsf_vertices: u64,
    pub max_hsf_face_values: u64,
    pub max_scene_meshes: u64,
    pub max_scene_primitives: u64,
    pub max_scene_views: u64,
    pub max_scene_definitions: u64,
    pub max_scene_nodes: u64,
    pub max_scene_instances: u64,
    pub max_scene_depth: u64,
    pub max_scene_visits: u64,
    pub max_scene_triangles: u64,
    pub max_file_bytes: u64,
    pub max_entries: u64,
    pub max_entry_bytes: u64,
    pub max_expanded_bytes: u64,
    pub max_output_bytes: u64,
    pub max_compression_ratio: u64,
    pub max_name_bytes: u64,
    pub max_xml_bytes: u64,
    pub max_xml_depth: u64,
    pub max_xml_elements: u64,
    pub max_hsf_records: u64,
    pub max_hsf_domains: u64,
    pub max_hsf_segment_depth: u64,
    pub max_hsf_string_bytes: u64,
}
impl Default for Limits {
    fn default() -> Self {
        Self::desktop()
    }
}
impl Limits {
    pub fn desktop() -> Self {
        Self {
            max_file_bytes: 256 << 20,
            max_hsf_image_pixels: 16_777_216,
            max_hsf_vertices: 10_000_000,
            max_hsf_face_values: 50_000_000,
            max_scene_meshes: 250_000,
            max_scene_primitives: 250_000,
            max_scene_views: 10_000,
            max_scene_definitions: 10_000,
            max_scene_nodes: 250_000,
            max_scene_instances: 1_000_000,
            max_scene_depth: 256,
            max_scene_visits: 2_000_000,
            max_scene_triangles: 10_000_000,
            max_entries: 4096,
            max_entry_bytes: 256 << 20,
            max_expanded_bytes: 512 << 20,
            // Desktop reads keep the eleven-configuration assembly (2.4 GB of
            // charges for 1.45 GB of process memory) within reach.
            max_output_bytes: 3072 << 20,
            max_compression_ratio: 1000,
            max_name_bytes: 4096,
            max_xml_bytes: 8 << 20,
            max_xml_depth: 128,
            max_xml_elements: 100_000,
            max_hsf_records: 1_000_000,
            max_hsf_domains: 128,
            max_hsf_segment_depth: 256,
            max_hsf_string_bytes: 16 << 20,
        }
    }
    pub fn service() -> Self {
        Self {
            max_file_bytes: 32 << 20,
            max_hsf_image_pixels: 4_194_304,
            max_hsf_vertices: 1_000_000,
            max_hsf_face_values: 5_000_000,
            max_scene_meshes: 250_000,
            max_scene_primitives: 250_000,
            max_scene_views: 1_000,
            max_scene_definitions: 1_000,
            max_scene_nodes: 250_000,
            max_scene_instances: 1_000_000,
            max_scene_depth: 64,
            max_scene_visits: 5_000_000,
            max_scene_triangles: 10_000_000,
            max_entries: 512,
            max_entry_bytes: 64 << 20,
            max_expanded_bytes: 256 << 20,
            // Sized for an eleven-configuration eDrawings assembly read one
            // configuration at a time (745k records, 87k nodes: about 2.0 GB of
            // charges for 1.45 GB of process memory).
            max_output_bytes: 2560 << 20,
            max_compression_ratio: 200,
            max_name_bytes: 1024,
            max_xml_bytes: 2 << 20,
            max_xml_depth: 64,
            max_xml_elements: 20_000,
            max_hsf_records: 2_000_000,
            max_hsf_domains: 32,
            max_hsf_segment_depth: 64,
            max_hsf_string_bytes: 2 << 20,
        }
    }
    pub fn budget(&self) -> hsf_core::Budget {
        hsf_core::Budget::new(hsf_core::Limits {
            max_input_bytes: self.max_file_bytes,
            max_expanded_bytes: self.max_expanded_bytes,
            max_output_bytes: self.max_output_bytes,
        })
    }
}
pub(crate) fn bound(value: u64, max: u64, code: &str) -> Result<(), Error> {
    if value > max {
        Err(Error::limit(code, &format!("{value} exceeds limit {max}")))
    } else {
        Ok(())
    }
}
