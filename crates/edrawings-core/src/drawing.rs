use crate::*;

/// Primitive inventory, not a projected/rendered native drawing. Segment names
/// and option strings are evidence, not authoritative sheet/component IDs.
#[derive(Clone, Debug)]
pub struct DrawingResult {
    scene: SceneResult,
    assessment: DrawingAssessment,
    user_option_records: Vec<UserOptionRecord>,
    component_inventory: ComponentInventory,
    configuration_inventory: ConfigurationInventory,
    sheet_inventory: SheetInventory,
    drawing_plane_profile: DrawingPlaneProfile,
}
impl DrawingResult {
    pub(crate) fn new(
        mut scene: SceneResult,
        mode: HsfMode,
        budget: &mut hsf_core::Budget,
    ) -> Result<Self, Error> {
        let mut diagnostic = Diagnostic::new(
            "drawing.document_semantics_unverified",
            Status::Unsupported,
            "drawing",
            "Complete document rendering, active selection and CAD dimension semantics remain unverified; stored inventories and bounded drawing-plane profiles report their own coverage",
        );
        diagnostic.entry_id = Some(scene.summary().hsf.entry_id.clone());
        if matches!(mode, HsfMode::Strict) {
            return Err(Error::Format(Box::new(diagnostic)));
        }
        diagnostic.severity = "warning".into();
        let user_option_records =
            crate::user_options::parse_records(&scene.summary().user_options, budget)?;
        let component_inventory = crate::components::inventory(&scene, budget)?;
        let configuration_inventory =
            crate::configurations::inventory(scene.summary(), &user_option_records, budget)?;
        let sheet_inventory =
            crate::sheets::inventory(scene.summary(), &user_option_records, budget)?;
        let drawing_plane_profile =
            crate::drawing_plane::profile(&scene, &user_option_records, &sheet_inventory, budget)?;
        scene.update_output_usage(budget);
        Ok(Self {
            scene,
            user_option_records,
            component_inventory,
            configuration_inventory,
            sheet_inventory,
            drawing_plane_profile,
            assessment: DrawingAssessment {
                status: Status::Partial,
                sheet_status: Status::Unsupported,
                view_status: Status::Unsupported,
                dimension_status: Status::Unsupported,
                configuration_status: Status::Unsupported,
                component_status: Status::Unsupported,
                diagnostics: vec![diagnostic],
            },
        })
    }
    pub fn summary(&self) -> DrawingSummary<'_> {
        DrawingSummary {
            assessment: &self.assessment,
            scene: self.scene.summary(),
            user_option_records: &self.user_option_records,
            component_inventory: &self.component_inventory,
            configuration_inventory: &self.configuration_inventory,
            sheet_inventory: &self.sheet_inventory,
            drawing_plane_profile: &self.drawing_plane_profile,
        }
    }
    pub fn scene(&self) -> &SceneResult {
        &self.scene
    }
}
