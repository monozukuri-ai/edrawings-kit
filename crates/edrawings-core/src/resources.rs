use crate::{
    ByteRange, EntryInfo, Error, Extraction, ExtractionInfo, Limits, SourceRef, Status,
    limits::bound, sha256,
};
use flate2::{Decompress, FlushDecompress, Status as InflateStatus};

pub(crate) fn extract(
    data: &[u8],
    entry: &EntryInfo,
    hash: &str,
    limits: &Limits,
    budget: &mut hsf_core::Budget,
) -> Result<Extraction, Error> {
    if entry.extraction_status == Status::Unsupported {
        return Err(Error::unsupported(
            "zip.unsupported_entry",
            "extraction",
            "Encryption, flags or compression method unsupported",
        ));
    }
    bound(entry.bytes, limits.max_entry_bytes, "limits.entry_bytes")?;
    if entry.compressed_bytes == 0 {
        if entry.bytes != 0 {
            return Err(Error::invalid(
                "zip.invalid_size",
                "extraction",
                "Nonempty entry has zero compressed length",
            ));
        }
    } else if entry.bytes
        > entry
            .compressed_bytes
            .saturating_mul(limits.max_compression_ratio)
    {
        return Err(Error::limit(
            "limits.compression_ratio",
            "Declared compression ratio exceeds limit",
        ));
    }
    let start = usize::try_from(entry.data_range.offset)
        .map_err(|_| Error::limit("limits.address_space", "Offset exceeds address space"))?;
    let len = usize::try_from(entry.data_range.length)
        .map_err(|_| Error::limit("limits.address_space", "Length exceeds address space"))?;
    let input = start
        .checked_add(len)
        .and_then(|end| data.get(start..end))
        .ok_or_else(|| {
            Error::invalid(
                "zip.invalid_range",
                "extraction",
                "Payload outside original bytes",
            )
        })?;
    // Charge before allocation. Decompression is capped at the advertised length;
    // an understated size is rejected before any extra byte is retained.
    budget.charge_expanded(entry.bytes)?;
    budget.charge_output(entry.bytes)?;
    let size = usize::try_from(entry.bytes)
        .map_err(|_| Error::limit("limits.address_space", "Output exceeds address space"))?;
    let mut output = Vec::new();
    output
        .try_reserve_exact(size)
        .map_err(|_| Error::limit("limits.allocation", "Cannot reserve output buffer"))?;
    if entry.compression_method == 0 {
        if input.len() != size {
            return Err(Error::invalid(
                "zip.invalid_size",
                "extraction",
                "Stored entry sizes differ",
            ));
        }
        output.extend_from_slice(input);
    } else if entry.compression_method == 8 {
        let mut decoder = Decompress::new(false);
        let mut chunk = [0u8; 32768];
        loop {
            let before_in = decoder.total_in();
            let before_out = decoder.total_out();
            let remaining = size - output.len();
            let capacity = chunk.len().min(remaining.saturating_add(1));
            let status = decoder
                .decompress(
                    &input[before_in as usize..],
                    &mut chunk[..capacity],
                    FlushDecompress::None,
                )
                .map_err(|_| {
                    Error::invalid(
                        "zip.invalid_deflate",
                        "extraction",
                        "Invalid DEFLATE stream",
                    )
                })?;
            let produced = (decoder.total_out() - before_out) as usize;
            if produced > remaining {
                return Err(Error::invalid(
                    "zip.invalid_size",
                    "extraction",
                    "Expanded size exceeds declared size",
                ));
            }
            output.extend_from_slice(&chunk[..produced]);
            if status == InflateStatus::StreamEnd {
                if decoder.total_in() != input.len() as u64 || output.len() != size {
                    return Err(Error::invalid(
                        "zip.invalid_size",
                        "extraction",
                        "Trailing compressed bytes or expanded size mismatch",
                    ));
                }
                break;
            }
            if before_in == decoder.total_in() && before_out == decoder.total_out() {
                return Err(Error::invalid(
                    "zip.truncated_deflate",
                    "extraction",
                    "DEFLATE stream has no complete terminator",
                ));
            }
        }
    } else {
        return Err(Error::unsupported(
            "zip.compression",
            "extraction",
            "Compression method unsupported",
        ));
    }
    let crc_status = if let Some(expected) = &entry.crc32 {
        if format!("{:08x}", crc32fast::hash(&output)) != *expected {
            return Err(Error::invalid(
                "zip.crc_mismatch",
                "extraction",
                "Entry CRC32 mismatch",
            ));
        }
        "verified"
    } else {
        "not_applicable"
    };
    let payload_hash = sha256(&output);
    let source = SourceRef {
        file_sha256: hash.into(),
        entry_id: entry.id.clone(),
        domain_id: format!("{}:decoded", entry.id),
        decoded_range: ByteRange {
            offset: 0,
            length: entry.bytes,
        },
        container_range: entry.data_range.clone(),
        encoding: if entry.crc32.is_none() {
            "identity"
        } else if entry.compression_method == 0 {
            "zip_store"
        } else {
            "zip_deflate"
        }
        .into(),
        payload_sha256: payload_hash.clone(),
    };
    Ok(Extraction {
        data: output,
        info: ExtractionInfo {
            entry_id: entry.id.clone(),
            bytes: entry.bytes,
            sha256: payload_hash,
            crc_status: crc_status.into(),
            source,
        },
    })
}
