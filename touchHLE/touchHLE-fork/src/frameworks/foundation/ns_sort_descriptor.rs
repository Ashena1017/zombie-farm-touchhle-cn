/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSSortDescriptor`.

use super::{
    NSComparisonResult, NSOrderedAscending, NSOrderedDescending, NSOrderedSame, NSUInteger,
};
use crate::objc::{
    autorelease, id, msg, msg_class, msg_send, nil, objc_classes, release, retain, ClassExports,
    HostObject, NSZonePtr, SEL,
};
use crate::Environment;

struct NSSortDescriptorHostObject {
    /// `NSString *`
    key: id,
    ascending: bool,
    selector: Option<SEL>,
}
impl HostObject for NSSortDescriptorHostObject {}

pub fn compare_objects_using_descriptors(
    env: &mut Environment,
    lhs: id,
    rhs: id,
    descriptors: id,
) -> NSComparisonResult {
    let count: NSUInteger = msg![env; descriptors count];
    for idx in 0..count {
        let descriptor: id = msg![env; descriptors objectAtIndex:idx];
        let result: NSComparisonResult = msg![env; descriptor compareObject:lhs toObject:rhs];
        if result != NSOrderedSame {
            return result;
        }
    }
    NSOrderedSame
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSSortDescriptor: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSSortDescriptorHostObject {
        key: nil,
        ascending: true,
        selector: None,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)sortDescriptorWithKey:(id)key ascending:(bool)ascending {
    let descriptor: id = msg![env; this alloc];
    let descriptor: id = msg![env; descriptor initWithKey:key ascending:ascending];
    autorelease(env, descriptor)
}

+ (id)sortDescriptorWithKey:(id)key ascending:(bool)ascending selector:(SEL)selector {
    let descriptor: id = msg![env; this alloc];
    let descriptor: id = msg![env; descriptor initWithKey:key ascending:ascending selector:selector];
    autorelease(env, descriptor)
}

- (id)initWithKey:(id)key ascending:(bool)ascending {
    let selector = env.objc.lookup_selector("compare:").unwrap();
    msg![env; this initWithKey:key ascending:ascending selector:selector]
}

- (id)initWithKey:(id)key ascending:(bool)ascending selector:(SEL)selector {
    retain(env, key);
    let host_obj = env.objc.borrow_mut::<NSSortDescriptorHostObject>(this);
    host_obj.key = key;
    host_obj.ascending = ascending;
    host_obj.selector = Some(selector);
    this
}

- (())dealloc {
    let key = std::mem::replace(&mut env.objc.borrow_mut::<NSSortDescriptorHostObject>(this).key, nil);
    release(env, key);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (id)copyWithZone:(NSZonePtr)_zone {
    let host_obj = env.objc.borrow::<NSSortDescriptorHostObject>(this);
    let key = host_obj.key;
    let ascending = host_obj.ascending;
    let selector = host_obj
        .selector
        .unwrap_or_else(|| env.objc.lookup_selector("compare:").unwrap());
    let descriptor: id = msg_class![env; NSSortDescriptor alloc];
    msg![env; descriptor initWithKey:key ascending:ascending selector:selector]
}

- (id)key {
    env.objc.borrow::<NSSortDescriptorHostObject>(this).key
}

- (bool)ascending {
    env.objc.borrow::<NSSortDescriptorHostObject>(this).ascending
}

- (SEL)selector {
    env.objc
        .borrow::<NSSortDescriptorHostObject>(this)
        .selector
        .unwrap_or_else(|| env.objc.lookup_selector("compare:").unwrap())
}

- (id)reversedSortDescriptor {
    let (key, ascending, selector) = {
        let host_obj = env.objc.borrow::<NSSortDescriptorHostObject>(this);
        (
            host_obj.key,
            host_obj.ascending,
            host_obj
                .selector
                .unwrap_or_else(|| env.objc.lookup_selector("compare:").unwrap()),
        )
    };
    let descriptor: id = msg_class![env; NSSortDescriptor alloc];
    let descriptor: id = msg![env; descriptor initWithKey:key
                                               ascending:(!ascending)
                                                selector:selector];
    autorelease(env, descriptor)
}

- (NSComparisonResult)compareObject:(id)lhs toObject:(id)rhs {
    let (key, ascending, selector) = {
        let host_obj = env.objc.borrow::<NSSortDescriptorHostObject>(this);
        (
            host_obj.key,
            host_obj.ascending,
            host_obj
                .selector
                .unwrap_or_else(|| env.objc.lookup_selector("compare:").unwrap()),
        )
    };

    let lhs_value: id = if key == nil {
        lhs
    } else {
        msg![env; lhs valueForKey:key]
    };
    let rhs_value: id = if key == nil {
        rhs
    } else {
        msg![env; rhs valueForKey:key]
    };

    let mut result = match (lhs_value == nil, rhs_value == nil) {
        (true, true) => NSOrderedSame,
        (true, false) => NSOrderedAscending,
        (false, true) => NSOrderedDescending,
        (false, false) => msg_send(env, (lhs_value, selector, rhs_value)),
    };

    if !ascending {
        result = -result;
    }
    result
}

@end

};
