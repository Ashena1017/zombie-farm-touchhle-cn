/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Read-only object-registry inspection for opt-in memory-write diagnostics.

use super::{id, ObjC};
use crate::mem::{GuestUSize, Mem};

#[derive(Debug)]
pub(crate) struct RegisteredObjectMemoryOverlap {
    pub object: id,
    pub allocation_size: Option<GuestUSize>,
    pub isa: Option<u32>,
    pub class_name: Option<String>,
}

fn ranges_overlap(a: u64, a_size: u64, b: u64, b_size: u64) -> bool {
    a_size != 0
        && b_size != 0
        && a < b.saturating_add(b_size)
        && b < a.saturating_add(a_size)
}

impl ObjC {
    /// Inspect registered objects intersecting a guest write span. No guest
    /// calls, refcount changes, guest allocation, or mutation of guest bytes.
    /// Unknown allocation sizes only provide the four-byte object header;
    /// they must not be interpreted as proof of a missing allocation.
    pub(crate) fn registered_objects_in_range(
        &self,
        mem: &mut Mem,
        start: u32,
        size: u64,
        limit: usize,
    ) -> Vec<RegisteredObjectMemoryOverlap> {
        if size == 0 || limit == 0 {
            return Vec::new();
        }
        let end = u64::from(start).saturating_add(size);
        let mut objects: Vec<id> = self
            .objects
            .keys()
            .copied()
            .filter(|object| u64::from(object.to_bits()) < end)
            .collect();
        objects.sort_unstable_by_key(|object| object.to_bits());
        let mut overlaps = Vec::new();
        for object in objects {
            let allocation_size = mem.try_malloc_size(object.cast_const().cast());
            let extent = u64::from(allocation_size.unwrap_or(4));
            if !ranges_overlap(u64::from(object.to_bits()), extent, u64::from(start), size) {
                continue;
            }
            // A corrupted isa is data, not a pointer to dereference. The
            // fallible debugger reader avoids adding a diagnostic panic.
            let isa = mem
                .get_bytes_fallible(object.cast_const().cast(), 4)
                .map(|bytes| u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]));
            let class_name = isa
                .and_then(|isa| self.try_get_class_name(id::from_bits(isa)))
                .map(str::to_owned);
            overlaps.push(RegisteredObjectMemoryOverlap {
                object,
                allocation_size,
                isa,
                class_name,
            });
            if overlaps.len() >= limit {
                break;
            }
        }
        overlaps
    }
}

#[cfg(test)]
mod tests {
    use super::ranges_overlap;

    #[test]
    fn write_span_overlap_includes_object_tail_but_not_adjacent_bytes() {
        assert!(ranges_overlap(0x1000, 0x100, 0x1080, 0x20));
        assert!(ranges_overlap(0x1080, 0x20, 0x1000, 0x100));
        assert!(!ranges_overlap(0x1000, 0x100, 0x1100, 0x20));
        assert!(!ranges_overlap(0x1000, 0, 0x1000, 1));
        assert!(!ranges_overlap(0x1000, 1, 0x1000, 0));
    }
}
