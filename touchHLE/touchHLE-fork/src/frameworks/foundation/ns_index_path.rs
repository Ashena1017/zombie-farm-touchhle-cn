/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSIndexPath`.

use super::{
    NSComparisonResult, NSOrderedAscending, NSOrderedDescending, NSOrderedSame, NSUInteger,
};
use crate::mem::{ConstPtr, MutPtr};
use crate::objc::{
    autorelease, id, msg, nil, objc_classes, retain, ClassExports, HostObject, NSZonePtr,
};

#[derive(Default)]
struct NSIndexPathHostObject {
    indexes: Vec<NSUInteger>,
}
impl HostObject for NSIndexPathHostObject {}

fn allocate(env: &mut crate::Environment, class: id, indexes: Vec<NSUInteger>) -> id {
    env.objc.alloc_object(
        class,
        Box::new(NSIndexPathHostObject { indexes }),
        &mut env.mem,
    )
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSIndexPath: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    allocate(env, this, Vec::new())
}

+ (id)indexPathWithIndex:(NSUInteger)index {
    let path = allocate(env, this, vec![index]);
    autorelease(env, path)
}

+ (id)indexPathWithIndexes:(ConstPtr<NSUInteger>)indexes
                    length:(NSUInteger)length {
    let path: id = msg![env; this alloc];
    let path: id = msg![env; path initWithIndexes:indexes length:length];
    autorelease(env, path)
}

// These two constructors are UIKit additions used by UITableView and
// UICollectionView, but implementing them here keeps this small class cluster
// in one place.
+ (id)indexPathForRow:(i32)row inSection:(i32)section {
    let indexes = vec![section.try_into().unwrap(), row.try_into().unwrap()];
    let path = allocate(env, this, indexes);
    autorelease(env, path)
}

+ (id)indexPathForItem:(i32)item inSection:(i32)section {
    let indexes = vec![section.try_into().unwrap(), item.try_into().unwrap()];
    let path = allocate(env, this, indexes);
    autorelease(env, path)
}

- (id)initWithIndex:(NSUInteger)index {
    env.objc.borrow_mut::<NSIndexPathHostObject>(this).indexes = vec![index];
    this
}

- (id)initWithIndexes:(ConstPtr<NSUInteger>)indexes
                length:(NSUInteger)length {
    let mut result = Vec::with_capacity(length as usize);
    for position in 0..length {
        result.push(env.mem.read(indexes + position));
    }
    env.objc.borrow_mut::<NSIndexPathHostObject>(this).indexes = result;
    this
}

- (NSUInteger)length {
    env.objc.borrow::<NSIndexPathHostObject>(this).indexes.len().try_into().unwrap()
}

- (NSUInteger)indexAtPosition:(NSUInteger)position {
    env.objc.borrow::<NSIndexPathHostObject>(this)
        .indexes
        .get(position as usize)
        .copied()
        .unwrap_or(super::NSNotFound as NSUInteger)
}

- (i32)section {
    env.objc.borrow::<NSIndexPathHostObject>(this)
        .indexes
        .first()
        .copied()
        .unwrap_or(0)
        .try_into()
        .unwrap()
}

- (i32)row {
    env.objc.borrow::<NSIndexPathHostObject>(this)
        .indexes
        .get(1)
        .copied()
        .unwrap_or(0)
        .try_into()
        .unwrap()
}

- (i32)item {
    msg![env; this row]
}

- (id)indexPathByAddingIndex:(NSUInteger)index {
    let mut indexes = env.objc.borrow::<NSIndexPathHostObject>(this).indexes.clone();
    indexes.push(index);
    let class: id = msg![env; this class];
    let path = allocate(env, class, indexes);
    autorelease(env, path)
}

- (NSComparisonResult)compare:(id)other {
    if other == nil {
        return NSOrderedDescending;
    }
    let lhs = &env.objc.borrow::<NSIndexPathHostObject>(this).indexes;
    let rhs = &env.objc.borrow::<NSIndexPathHostObject>(other).indexes;
    match lhs.cmp(rhs) {
        std::cmp::Ordering::Less => NSOrderedAscending,
        std::cmp::Ordering::Equal => NSOrderedSame,
        std::cmp::Ordering::Greater => NSOrderedDescending,
    }
}

- (())getIndexes:(MutPtr<NSUInteger>)indexes {
    for (position, &index) in env
        .objc
        .borrow::<NSIndexPathHostObject>(this)
        .indexes
        .iter()
        .enumerate()
    {
        env.mem.write(indexes + position as u32, index);
    }
}

- (id)copyWithZone:(NSZonePtr)_zone {
    retain(env, this)
}

- (NSUInteger)hash {
    env.objc
        .borrow::<NSIndexPathHostObject>(this)
        .indexes
        .iter()
        .fold(0u32, |hash, &index| hash.wrapping_mul(31).wrapping_add(index))
}

- (())dealloc {
    env.objc.dealloc_object(this, &mut env.mem)
}
@end

};
