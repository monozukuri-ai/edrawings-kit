use crate::{Diagnostic, Error, InputKind, Limits, ProbeResult, hsf_adapter, limits::bound};

pub(crate) const PREFIX_LEN: usize = 92;
pub(crate) fn edrawings_prefix(data: &[u8]) -> bool {
    data.get(..20) == Some(b"[\x01\0\0\0\xbe\r2008+ archive")
}
pub fn probe_bytes(data: &[u8], limits: &Limits) -> Result<ProbeResult, Error> {
    bound(
        data.len() as u64,
        limits.max_file_bytes,
        "limits.file_bytes",
    )?;
    let mut result = ProbeResult {
        input_kind: InputKind::Unknown,
        evidence: vec![],
        header: None,
        diagnostics: vec![],
    };
    if data.starts_with(b";; HSF V") {
        result.input_kind = InputKind::RawHsf;
        result
            .evidence
            .push("HSF identification prefix; eDrawings origin is not established".into());
        match hsf_adapter::header(data) {
            Ok(h) => result.header = Some(h),
            Err(Error::Format(d)) => result.diagnostics.push(*d),
            Err(e) => return Err(e),
        }
    } else if edrawings_prefix(data) {
        result.input_kind = InputKind::PrefixedZip;
        result
            .evidence
            .push("Observed eDrawings 2008+ archive prefix (92-byte profile)".into());
    } else if data.starts_with(b"PK\x03\x04") || data.starts_with(b"PK\x05\x06") {
        result.input_kind = InputKind::Zip;
        result
            .evidence
            .push("ZIP signature; eDrawings contents have not been inspected".into());
    }
    Ok(result)
}

pub(crate) fn candidate_diagnostics(ids: &[String]) -> Vec<Diagnostic> {
    if ids.len() <= 1 {
        return vec![];
    }
    let mut d = Diagnostic::new(
        "hsf.ambiguous_candidates",
        crate::Status::Partial,
        "container",
        "Multiple HSF candidates; select an entry ID explicitly",
    );
    d.severity = "warning".into();
    vec![d]
}
