/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Minimal `UIPasteboard`.

use crate::frameworks::foundation::ns_array;
use crate::frameworks::foundation::ns_string::from_rust_string;
use crate::objc::{
    id, msg, nil, objc_classes, release, retain, ClassExports, HostObject, NSZonePtr,
};

#[derive(Default)]
struct UIPasteboardHostObject {
    name: id,
    string: id,
}
impl HostObject for UIPasteboardHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UIPasteboard: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::<UIPasteboardHostObject>::default(), &mut env.mem)
}

+ (id)generalPasteboard {
    let pasteboard: id = msg![env; this alloc];
    pasteboard
}

+ (id)pasteboardWithName:(id)name create:(bool)_create {
    let pasteboard: id = msg![env; this alloc];
    retain(env, name);
    env.objc.borrow_mut::<UIPasteboardHostObject>(pasteboard).name = name;
    pasteboard
}

+ (id)pasteboardWithUniqueName {
    let name = from_rust_string(env, "touchHLE.pasteboard".to_string());
    let pasteboard: id = msg![env; this pasteboardWithName:name create:true];
    release(env, name);
    pasteboard
}

+ (())removePasteboardWithName:(id)_name {
}

- (())dealloc {
    let name = env.objc.borrow::<UIPasteboardHostObject>(this).name;
    let string = env.objc.borrow::<UIPasteboardHostObject>(this).string;
    release(env, name);
    release(env, string);
    env.objc.dealloc_object(this, &mut env.mem)
}

- (id)name {
    env.objc.borrow::<UIPasteboardHostObject>(this).name
}

- (id)string {
    env.objc.borrow::<UIPasteboardHostObject>(this).string
}

- (())setString:(id)string {
    let old_string = env.objc.borrow::<UIPasteboardHostObject>(this).string;
    retain(env, string);
    release(env, old_string);
    env.objc.borrow_mut::<UIPasteboardHostObject>(this).string = string;
}

- (id)strings {
    let string = env.objc.borrow::<UIPasteboardHostObject>(this).string;
    if string == nil {
        ns_array::from_vec(env, Vec::new())
    } else {
        ns_array::from_vec(env, vec![string])
    }
}

- (())setStrings:(id)strings {
    let count: crate::frameworks::foundation::NSUInteger = msg![env; strings count];
    if count == 0 {
        () = msg![env; this setString:nil];
    } else {
        let first: id = msg![env; strings objectAtIndex:0];
        () = msg![env; this setString:first];
    }
}

- (id)pasteboardTypes {
    ns_array::from_vec(env, Vec::new())
}

- (bool)containsPasteboardTypes:(id)_pasteboard_types {
    false
}

- (id)dataForPasteboardType:(id)_pasteboard_type {
    nil
}

- (())setData:(id)_data forPasteboardType:(id)_pasteboard_type {
}

- (id)valueForPasteboardType:(id)_pasteboard_type {
    nil
}

- (())setValue:(id)_value forPasteboardType:(id)_pasteboard_type {
}

- (id)items {
    ns_array::from_vec(env, Vec::new())
}

- (())setItems:(id)_items {
}

- (())setPersistent:(bool)_persistent {
}

- (bool)isPersistent {
    false
}

@end

};
