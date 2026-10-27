//! Strict classic ZIP index. No signature scanning for local records, no extraction paths.
use crate::{ByteRange, Diagnostic, EntryInfo, Error, Limits, Status, limits::bound};

pub(crate) struct Index {
    pub entries: Vec<EntryInfo>,
    pub offset_base: u64,
    pub diagnostics: Vec<Diagnostic>,
}
fn invalid(message: &str) -> Error {
    Error::invalid("zip.invalid_structure", "container", message)
}
fn slice(data: &[u8], at: usize, len: usize) -> Result<&[u8], Error> {
    at.checked_add(len)
        .and_then(|end| data.get(at..end))
        .ok_or_else(|| invalid("Truncated or overflowing ZIP range"))
}
fn u16le(data: &[u8], at: usize) -> Result<u16, Error> {
    let b = slice(data, at, 2)?;
    Ok(u16::from_le_bytes([b[0], b[1]]))
}
fn u32le(data: &[u8], at: usize) -> Result<u32, Error> {
    let b = slice(data, at, 4)?;
    Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}
fn check_extra(mut bytes: &[u8]) -> Result<(), Error> {
    while !bytes.is_empty() {
        let tag = u16le(bytes, 0)?;
        let size = u16le(bytes, 2)? as usize;
        slice(bytes, 4, size)?;
        if tag == 1 {
            return Err(Error::unsupported(
                "zip.zip64",
                "container",
                "ZIP64 is not supported",
            ));
        }
        bytes = &bytes[4 + size..];
    }
    Ok(())
}
pub(crate) fn index(data: &[u8], prefix: usize, limits: &Limits) -> Result<Index, Error> {
    if data.len() < 22 {
        return Err(invalid("Missing ZIP end record"));
    }
    let lo = data.len().saturating_sub(22 + 65535);
    let eocd = (lo..=data.len() - 22)
        .rev()
        .find(|&at| {
            data.get(at..at + 4) == Some(b"PK\x05\x06")
                && u16le(data, at + 20).is_ok_and(|n| at + 22 + n as usize == data.len())
        })
        .ok_or_else(|| invalid("Missing ZIP end record or unexpected trailing bytes"))?;
    if eocd >= 20 && data.get(eocd - 20..eocd - 16) == Some(b"PK\x06\x07") {
        return Err(Error::unsupported(
            "zip.zip64",
            "container",
            "ZIP64 locator is unsupported",
        ));
    }
    let count = u16le(data, eocd + 10)?;
    let cd_size = u32le(data, eocd + 12)?;
    let cd_offset = u32le(data, eocd + 16)?;
    if count == u16::MAX || cd_size == u32::MAX || cd_offset == u32::MAX {
        return Err(Error::unsupported(
            "zip.zip64",
            "container",
            "ZIP64 sentinel is unsupported",
        ));
    }
    if u16le(data, eocd + 4)? != 0 || u16le(data, eocd + 6)? != 0 || u16le(data, eocd + 8)? != count
    {
        return Err(Error::unsupported(
            "zip.multi_disk",
            "container",
            "Multi-disk ZIP is unsupported",
        ));
    }
    bound(count as u64, limits.max_entries, "limits.entries")?;
    let cd_start = eocd
        .checked_sub(cd_size as usize)
        .ok_or_else(|| invalid("Invalid central directory length"))?;
    let base = cd_start
        .checked_sub(cd_offset as usize)
        .ok_or_else(|| invalid("Central directory offset exceeds position"))?;
    if (base != 0 && base != prefix) || cd_start < prefix {
        return Err(invalid(
            "ZIP offset base does not match the supported container prefix",
        ));
    }
    let mut cursor = cd_start;
    let mut entries = Vec::new();
    let mut occupied = Vec::new();
    let mut diagnostics = Vec::new();
    for ordinal in 0..count as usize {
        let fixed = slice(data, cursor, 46)?;
        if &fixed[..4] != b"PK\x01\x02" {
            return Err(invalid("Invalid central directory signature"));
        }
        let flags = u16le(fixed, 8)?;
        let method = u16le(fixed, 10)?;
        let crc = u32le(fixed, 16)?;
        let compressed = u32le(fixed, 20)?;
        let size = u32le(fixed, 24)?;
        let name_len = u16le(fixed, 28)? as usize;
        let extra_len = u16le(fixed, 30)? as usize;
        let comment_len = u16le(fixed, 32)? as usize;
        let offset = u32le(fixed, 42)?;
        if [compressed, size, offset].contains(&u32::MAX) || u16le(fixed, 34)? == u16::MAX {
            return Err(Error::unsupported(
                "zip.zip64",
                "container",
                "ZIP64 entry is unsupported",
            ));
        }
        if u16le(fixed, 34)? != 0 {
            return Err(Error::unsupported(
                "zip.multi_disk",
                "container",
                "Entry resides on another disk",
            ));
        }
        bound(name_len as u64, limits.max_name_bytes, "limits.name_bytes")?;
        let raw_name = slice(data, cursor + 46, name_len)?;
        check_extra(slice(data, cursor + 46 + name_len, extra_len)?)?;
        let next = cursor + 46 + name_len + extra_len + comment_len;
        if next > eocd {
            return Err(invalid(
                "Central directory entry exceeds its declared region",
            ));
        }
        let at = (offset as usize)
            .checked_add(base)
            .ok_or_else(|| invalid("Local offset overflow"))?;
        if at < prefix {
            return Err(invalid("Local header points into prefix"));
        }
        let local = slice(data, at, 30)?;
        if &local[..4] != b"PK\x03\x04" || u16le(local, 6)? != flags || u16le(local, 8)? != method {
            return Err(invalid(
                "Local and central header signature/flags/method mismatch",
            ));
        }
        let ln = u16le(local, 26)? as usize;
        let le = u16le(local, 28)? as usize;
        if slice(data, at + 30, ln)? != raw_name {
            return Err(invalid("Local and central entry names differ"));
        }
        check_extra(slice(data, at + 30 + ln, le)?)?;
        let start = at + 30 + ln + le;
        let end = start
            .checked_add(compressed as usize)
            .ok_or_else(|| invalid("Payload range overflow"))?;
        if end > cd_start {
            return Err(invalid("Entry payload overlaps central directory"));
        }
        let local_values = [u32le(local, 14)?, u32le(local, 18)?, u32le(local, 22)?];
        let values = [crc, compressed, size];
        let mut record_end = end;
        if flags & 8 == 0 {
            if local_values != values {
                return Err(invalid("Local and central CRC/size mismatch"));
            }
        } else {
            if local_values
                .iter()
                .zip(values)
                .any(|(&v, w)| v != 0 && v != w)
            {
                return Err(invalid("Nonzero local descriptor values disagree"));
            }
            // Descriptor signatures are optional, and a CRC can equal the signature.
            let candidates = [end, end + 4];
            let valid = candidates.into_iter().find(|&pos| {
                if pos != end && data.get(end..end + 4) != Some(b"PK\x07\x08") {
                    return false;
                }
                pos.checked_add(12).is_some_and(|n| n <= cd_start)
                    && values
                        .iter()
                        .enumerate()
                        .all(|(i, &v)| u32le(data, pos + i * 4).is_ok_and(|x| x == v))
            });
            record_end =
                valid.ok_or_else(|| invalid("Missing or inconsistent data descriptor"))? + 12;
        }
        occupied.push((at, record_end));
        let id = format!("entry:{ordinal}");
        let (name, encoding) = if flags & 0x800 != 0 {
            (
                std::str::from_utf8(raw_name)
                    .map_err(|_| invalid("Invalid UTF-8 entry name"))?
                    .to_owned(),
                "utf-8",
            )
        } else if raw_name.is_ascii() {
            (String::from_utf8_lossy(raw_name).into_owned(), "ascii")
        } else {
            // Preserve raw bytes; do not mislabel a lossy display name as decoded CP437.
            let mut d = Diagnostic::new(
                "zip.name_encoding",
                Status::Partial,
                "container",
                "Legacy non-ASCII name retained as raw bytes; display is lossy",
            )
            .entry(&id);
            d.severity = "warning".into();
            diagnostics.push(d);
            (String::from_utf8_lossy(raw_name).into_owned(), "legacy_raw")
        };
        let supported_flags = 0x800 | 8 | if method == 8 { 6 } else { 0 };
        let supported = flags & !supported_flags == 0 && matches!(method, 0 | 8);
        if !supported {
            let mut d = Diagnostic::new(
                "zip.unsupported_entry",
                Status::Unsupported,
                "extraction",
                "Entry uses encryption, unsupported flags, or compression",
            )
            .entry(&id);
            d.severity = "warning".into();
            diagnostics.push(d);
        }
        let role = match raw_name {
            b"eModel" => "hsf",
            b"preview.jpg" | b"preview.png" => "preview",
            b"materials.xml" | b"scene.xml" => "metadata",
            b"OLE" => "ole",
            _ => "unknown",
        };
        entries.push(EntryInfo {
            id,
            ordinal,
            name,
            raw_name: raw_name.to_vec(),
            name_encoding: encoding.into(),
            role: role.into(),
            compressed_bytes: compressed as u64,
            bytes: size as u64,
            compression_method: method,
            flag_bits: flags,
            crc32: Some(format!("{crc:08x}")),
            crc_status: "not_checked".into(),
            header_range: ByteRange {
                offset: at as u64,
                length: (start - at) as u64,
            },
            data_range: ByteRange {
                offset: start as u64,
                length: compressed as u64,
            },
            extraction_status: if supported {
                Status::NotRequested
            } else {
                Status::Unsupported
            },
        });
        cursor = next;
    }
    if cursor != eocd {
        return Err(invalid("Central directory size/count mismatch"));
    }
    occupied.sort_unstable();
    let mut last = prefix;
    for (start, end) in occupied {
        if start < last {
            return Err(invalid("Overlapping or aliased ZIP entries"));
        }
        // Accept a contiguous archive profile, without hidden local entries or padding.
        if start != last {
            return Err(Error::unsupported(
                "zip.unindexed_region",
                "container",
                "Unindexed bytes between ZIP entries",
            ));
        }
        last = end;
    }
    if last != cd_start {
        return Err(Error::unsupported(
            "zip.unindexed_region",
            "container",
            "Unindexed bytes before central directory",
        ));
    }
    Ok(Index {
        entries,
        offset_base: base as u64,
        diagnostics,
    })
}
