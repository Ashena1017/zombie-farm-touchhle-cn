/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! The `NSValue` class cluster, including `NSNumber`.

use super::ns_string::{from_rust_ordering, from_rust_string};
use super::{
    _nib_archive_decoder, ns_keyed_unarchiver, NSComparisonResult, NSOrderedSame, NSUInteger,
};
use crate::frameworks::core_foundation::cf_number::{
    kCFNumberCharType, kCFNumberFloat32Type, kCFNumberFloatType, kCFNumberIntType,
    kCFNumberSInt16Type, kCFNumberSInt32Type, kCFNumberSInt8Type, kCFNumberShortType, CFNumberType,
};
use crate::frameworks::core_graphics::{CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::ns_keyed_archiver::get_value_to_encode_for_current_key;
use crate::frameworks::foundation::NSInteger;
use crate::mem::{ConstPtr, ConstVoidPtr, GuestUSize, MutVoidPtr};
use crate::objc::{
    autorelease, id, msg, msg_class, nil, objc_classes, release, retain, Class, ClassExports,
    HostObject, NSZonePtr,
};
use crate::Environment;
use std::cmp::Ordering;

#[derive(Debug)]
pub(super) enum NSValueHostObject {
    CGPoint(CGPoint),
    CGSize(CGSize),
    CGRect(CGRect),
    Raw { bytes: Vec<u8>, objc_type: Vec<u8> },
}
impl HostObject for NSValueHostObject {}

fn align_up(value: usize, alignment: usize) -> Option<usize> {
    let remainder = value % alignment;
    if remainder == 0 {
        Some(value)
    } else {
        value.checked_add(alignment - remainder)
    }
}

fn skip_quoted_name(encoding: &[u8], mut index: usize) -> Option<usize> {
    if encoding.get(index) != Some(&b'"') {
        return Some(index);
    }
    index += 1;
    while encoding.get(index) != Some(&b'"') {
        index = index.checked_add(1)?;
    }
    Some(index + 1)
}

fn parse_decimal(encoding: &[u8], mut index: usize) -> Option<(usize, usize)> {
    let start = index;
    let mut value = 0usize;
    while let Some(digit @ b'0'..=b'9') = encoding.get(index).copied() {
        value = value
            .checked_mul(10)?
            .checked_add(usize::from(digit - b'0'))?;
        index += 1;
    }
    (index != start).then_some((value, index))
}

fn parse_objc_type(encoding: &[u8], mut index: usize) -> Option<(usize, usize, usize)> {
    while matches!(
        encoding.get(index),
        Some(b'r' | b'n' | b'N' | b'o' | b'O' | b'R' | b'V')
    ) {
        index += 1;
    }

    let type_code = *encoding.get(index)?;
    index += 1;
    let result = match type_code {
        b'c' | b'C' | b'B' => (1, 1, index),
        b's' | b'S' => (2, 2, index),
        b'i' | b'I' | b'l' | b'L' | b'f' => (4, 4, index),
        b'q' | b'Q' | b'd' => (8, 8, index),
        b'v' => (0, 1, index),
        b'*' | b'#' | b':' | b'?' => (4, 4, index),
        b'@' => {
            if encoding.get(index) == Some(&b'?') {
                index += 1;
            } else if encoding.get(index) == Some(&b'"') {
                index = skip_quoted_name(encoding, index)?;
            }
            (4, 4, index)
        }
        b'^' => {
            let (_, _, next) = parse_objc_type(encoding, index)?;
            (4, 4, next)
        }
        b'b' => {
            let (bits, next) = parse_decimal(encoding, index)?;
            ((bits + 7) / 8, 1, next)
        }
        b'[' => {
            let (count, next) = parse_decimal(encoding, index)?;
            let (element_size, element_alignment, next) = parse_objc_type(encoding, next)?;
            if encoding.get(next) != Some(&b']') {
                return None;
            }
            (
                count.checked_mul(element_size)?,
                element_alignment,
                next + 1,
            )
        }
        b'{' | b'(' => {
            let closing = if type_code == b'{' { b'}' } else { b')' };
            loop {
                match encoding.get(index) {
                    Some(b'=') => break,
                    Some(byte) if *byte == closing => return None,
                    Some(_) => index += 1,
                    None => return None,
                }
            }
            index += 1;

            let mut size = 0usize;
            let mut alignment = 1usize;
            while encoding.get(index) != Some(&closing) {
                index = skip_quoted_name(encoding, index)?;
                let (field_size, field_alignment, next) = parse_objc_type(encoding, index)?;
                alignment = alignment.max(field_alignment);
                if type_code == b'{' {
                    size = align_up(size, field_alignment)?.checked_add(field_size)?;
                } else {
                    size = size.max(field_size);
                }
                index = next;
            }
            (align_up(size, alignment)?, alignment, index + 1)
        }
        _ => return None,
    };
    Some(result)
}

fn objc_type_size(encoding: &[u8]) -> Option<usize> {
    let (size, _, end) = parse_objc_type(encoding, 0)?;
    (end == encoding.len()).then_some(size)
}

fn new_raw_value(
    env: &mut Environment,
    class: Class,
    value: ConstVoidPtr,
    objc_type: ConstPtr<u8>,
) -> id {
    if value.is_null() || objc_type.is_null() {
        return nil;
    }
    let objc_type = match env.mem.cstr_at_utf8(objc_type) {
        Ok(value) => value.as_bytes().to_vec(),
        Err(_) => return nil,
    };
    let Some(size) = objc_type_size(&objc_type) else {
        log!(
            "Warning: NSValue does not understand Objective-C type {:?}",
            String::from_utf8_lossy(&objc_type)
        );
        return nil;
    };
    let Ok(size): Result<GuestUSize, _> = size.try_into() else {
        return nil;
    };
    let bytes = env.mem.bytes_at(value.cast(), size).to_vec();
    let object = env.objc.alloc_object(
        class,
        Box::new(NSValueHostObject::Raw { bytes, objc_type }),
        &mut env.mem,
    );
    autorelease(env, object)
}

macro_rules! impl_AsValue {
    ($method_name:tt, $typ:tt) => {
        pub fn $method_name(&self) -> $typ {
            match self {
                // Cast to u8 is needed for float conversions
                NSNumberHostObject::Bool(x) => *x as u8 as _,
                NSNumberHostObject::UnsignedLongLong(x) => *x as _,
                NSNumberHostObject::UnsignedInt(x) => *x as _,
                NSNumberHostObject::Int(x) => *x as _,
                NSNumberHostObject::LongLong(x) => *x as _,
                NSNumberHostObject::Float(x) => *x as _,
                NSNumberHostObject::Double(x) => *x as _,
                NSNumberHostObject::Short(x) => *x as _,
                NSNumberHostObject::UnsignedShort(x) => *x as _,
                NSNumberHostObject::Char(x) => *x as _,
            }
        }
    };
}

#[derive(Debug)]
pub(super) enum NSNumberHostObject {
    Bool(bool),
    UnsignedLongLong(u64),
    UnsignedInt(u32),
    Int(i32), // Also covers Integer and Long since this is a 32-bit platform.
    LongLong(i64),
    Float(f32),
    Double(f64),
    Short(i16),
    UnsignedShort(u16),
    Char(i8),
}
impl HostObject for NSNumberHostObject {}

impl NSNumberHostObject {
    fn as_bool(&self) -> bool {
        match self {
            NSNumberHostObject::Bool(x) => *x,
            NSNumberHostObject::UnsignedLongLong(x) => *x != 0,
            NSNumberHostObject::UnsignedInt(x) => *x != 0,
            NSNumberHostObject::Int(x) => *x != 0,
            NSNumberHostObject::LongLong(x) => *x != 0,
            NSNumberHostObject::Float(x) => *x != 0.0,
            NSNumberHostObject::Double(x) => *x != 0.0,
            NSNumberHostObject::Short(x) => *x != 0,
            NSNumberHostObject::UnsignedShort(x) => *x != 0,
            NSNumberHostObject::Char(x) => *x != 0,
        }
    }
    fn is_float(&self) -> bool {
        matches!(
            self,
            NSNumberHostObject::Float(_) | NSNumberHostObject::Double(_)
        )
    }
    impl_AsValue!(as_int, i32);
    impl_AsValue!(as_long_long, i64);
    impl_AsValue!(as_unsigned_long_long, u64);
    impl_AsValue!(as_unsigned_int, u32);
    impl_AsValue!(as_float, f32);
    impl_AsValue!(as_double, f64);
    impl_AsValue!(as_short, i16);
    impl_AsValue!(as_unsigned_short, u16);
    impl_AsValue!(as_char, i8);
    impl_AsValue!(as_i128, i128);
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

// NSValue is an abstract class. None of the things it should provide are
// implemented here yet (TODO).
@implementation NSValue: NSObject

+ (id)value:(ConstVoidPtr)value withObjCType:(ConstPtr<u8>)objc_type {
    new_raw_value(env, this, value, objc_type)
}

+ (id)valueWithBytes:(ConstVoidPtr)value objCType:(ConstPtr<u8>)objc_type {
    new_raw_value(env, this, value, objc_type)
}

+ (id)valueWithPointer:(ConstVoidPtr)ptr {
    // TODO: implement with `value:withObjCType:` instead
    msg_class![env; NSNumber numberWithUnsignedInt:(ptr.to_bits())]
}

+ (id)valueWithCGPoint:(CGPoint)value {
    let host_object = Box::new(NSValueHostObject::CGPoint(value));
    let new = env.objc.alloc_object(this, host_object, &mut env.mem);
    autorelease(env, new)
}

+ (id)valueWithCGSize:(CGSize)value {
    let host_object = Box::new(NSValueHostObject::CGSize(value));
    let new = env.objc.alloc_object(this, host_object, &mut env.mem);
    autorelease(env, new)
}

+ (id)valueWithCGRect:(CGRect)value {
    let host_object = Box::new(NSValueHostObject::CGRect(value));
    let new = env.objc.alloc_object(this, host_object, &mut env.mem);
    autorelease(env, new)
}

- (CGPoint)CGPointValue {
    let host_object = env.objc.borrow::<NSValueHostObject>(this);
    match host_object {
        NSValueHostObject::CGPoint(cg_point) => *cg_point,
        _ => unimplemented!()
    }
}

- (CGSize)CGSizeValue {
    let host_object = env.objc.borrow::<NSValueHostObject>(this);
    match host_object {
        NSValueHostObject::CGSize(cg_size) => *cg_size,
        _ => unimplemented!()
    }
}

- (CGRect)CGRectValue {
    let host_object = env.objc.borrow::<NSValueHostObject>(this);
    match host_object {
        NSValueHostObject::CGRect(cg_rect) => *cg_rect,
        _ => unimplemented!()
    }
}

- (())getValue:(MutVoidPtr)value {
    if value.is_null() {
        return;
    }
    match env.objc.borrow::<NSValueHostObject>(this) {
        NSValueHostObject::CGPoint(point) => env.mem.write(value.cast(), *point),
        NSValueHostObject::CGSize(size) => env.mem.write(value.cast(), *size),
        NSValueHostObject::CGRect(rect) => env.mem.write(value.cast(), *rect),
        NSValueHostObject::Raw { bytes, .. } => {
            let byte_count: GuestUSize = bytes.len().try_into().unwrap();
            env.mem
                .bytes_at_mut(value.cast(), byte_count)
                .copy_from_slice(bytes);
        }
    }
}

- (ConstPtr<u8>)objCType {
    let encoding: &[u8] = match env.objc.borrow::<NSValueHostObject>(this) {
        NSValueHostObject::CGPoint(_) => b"{CGPoint=ff}",
        NSValueHostObject::CGSize(_) => b"{CGSize=ff}",
        NSValueHostObject::CGRect(_) => b"{CGRect={CGPoint=ff}{CGSize=ff}}",
        NSValueHostObject::Raw { objc_type, .. } => objc_type,
    };
    env.mem.alloc_and_write_cstr(encoding).cast_const()
}

// NSCopying implementation
- (id)copyWithZone:(NSZonePtr)_zone {
    retain(env, this)
}

- (MutVoidPtr)pointerValue {
    let class: Class = msg![env; this class];
    assert!(class == env.objc.get_known_class("NSNumber", &mut env.mem));
    // According to the docs, `If the value object was not created to hold
    // a pointer-sized data item, the result is undefined.`
    let val = msg![env; this unsignedIntValue];
    MutVoidPtr::from_bits(val)
}

@end

// NSNumber is not an abstract class.
@implementation NSNumber: NSValue

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSNumberHostObject::Bool(false));
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)numberWithBool:(bool)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithBool:value];
    autorelease(env, new)
}

+ (id)numberWithFloat:(f32)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithFloat:value];
    autorelease(env, new)
}

+ (id)numberWithDouble:(f64)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithDouble:value];
    autorelease(env, new)
}

+ (id)numberWithUnsignedInt:(u32)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithUnsignedInt:value];
    autorelease(env, new)
}

+ (id)numberWithInt:(i32)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithInt:value];
    autorelease(env, new)
}

+ (id)numberWithLong:(i32)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithLong:value];
    autorelease(env, new)
}

+ (id)numberWithInteger:(NSInteger)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithInteger:value];
    autorelease(env, new)
}

+ (id)numberWithLongLong:(i64)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithLongLong:value];
    autorelease(env, new)
}

+ (id)numberWithUnsignedLongLong:(u64)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithUnsignedLongLong:value];
    autorelease(env, new)
}

+ (id)numberWithShort:(i16)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithShort:value];
    autorelease(env, new)
}

+ (id)numberWithUnsignedShort:(u16)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithUnsignedShort:value];
    autorelease(env, new)
}

+ (id)numberWithChar:(i8)value {
    // TODO: for greater efficiency we could return a static-lifetime value

    let new: id = msg![env; this alloc];
    let new: id = msg![env; new initWithChar:value];
    autorelease(env, new)
}

// TODO: types other than booleans and long longs

// NSCoding implementation
- (id)initWithCoder:(id)coder {
    let class: Class = msg![env; coder class];
    let keyed_unarch_class: Class = msg_class![env; NSKeyedUnarchiver class];
    let nib_archive_class: Class = msg_class![env; _touchHLE_NIBArchiveDecoder class];
    let new_num = if env.objc.class_is_subclass_of(class, keyed_unarch_class) {
        ns_keyed_unarchiver::decode_current_number(env, coder)
    } else if env.objc.class_is_subclass_of(class, nib_archive_class) {
        _nib_archive_decoder::decode_current_number(env, coder)
    } else {
        unimplemented!();
    };
    release(env, this);
    new_num
}
- (())encodeWithCoder:(id)coder {
    let host_object = env.objc.borrow::<NSNumberHostObject>(this);
    let (key, val) = match host_object {
        NSNumberHostObject::Bool(value) => ("NS.intval", plist::Value::Integer((*value as i64).into())),
        NSNumberHostObject::Char(value) => ("NS.intval", plist::Value::Integer((*value as i64).into())),
        NSNumberHostObject::Short(value) => ("NS.intval", plist::Value::Integer((*value as i64).into())),
        NSNumberHostObject::UnsignedShort(value) => ("NS.intval", plist::Value::Integer((*value as u64).into())),
        NSNumberHostObject::UnsignedInt(value) => ("NS.intval", plist::Value::Integer((*value as u64).into())),
        NSNumberHostObject::UnsignedLongLong(value) => ("NS.intval", plist::Value::Integer((*value).into())),
        NSNumberHostObject::Int(i) => ("NS.intval", plist::Value::Integer((*i).into())),
        NSNumberHostObject::LongLong(value) => ("NS.intval", plist::Value::Integer((*value).into())),
        NSNumberHostObject::Float(value) => ("NS.dblval", plist::Value::Real((*value).into())),
        NSNumberHostObject::Double(d) => ("NS.dblval", plist::Value::Real(*d)),
    };

    let scope = get_value_to_encode_for_current_key(env, coder);
    scope.insert(key.to_string(), val);
}

- (id)initWithBool:(bool)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Bool(value);
    this
}

- (id)initWithFloat:(f32)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Float(value);
    this
}

- (id)initWithDouble:(f64)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Double(value);
    this
}

- (id)initWithLongLong:(i64)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::LongLong(value);
    this
}

- (id)initWithUnsignedInt:(u32)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::UnsignedInt(value);
    this
}

- (id)initWithInt:(i32)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Int(value);
    this
}

- (id)initWithLong:(i32)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Int(value);
    this
}

- (id)initWithInteger:(NSInteger)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Int(value);
    this
}

- (id)initWithUnsignedLongLong:(u64)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::UnsignedLongLong(value);
    this
}

- (id)initWithShort:(i16)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Short(value);
    this
}

- (id)initWithUnsignedShort:(u16)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::UnsignedShort(value);
    this
}

- (id)initWithChar:(i8)value {
    *env.objc.borrow_mut(this) = NSNumberHostObject::Char(value);
    this
}

- (bool)boolValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_bool()
}

- (NSInteger)integerValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_int()
}

- (i32)intValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_int()
}

- (i32)longValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_int()
}

- (f32)floatValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_float()
}

- (f64)doubleValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_double()
}

- (i64)longLongValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_long_long()
}

- (u64)unsignedLongLongValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_unsigned_long_long()
}

- (u32)unsignedIntValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_unsigned_int()
}

- (NSUInteger)unsignedIntegerValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_unsigned_int()
}

- (i16)shortValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_short()
}

- (u16)unsignedShortValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_unsigned_short()
}

- (i8)charValue {
    env.objc.borrow::<NSNumberHostObject>(this).as_char()
}

- (ConstPtr<u8>)objCType {
    let encoding = match env.objc.borrow::<NSNumberHostObject>(this) {
        NSNumberHostObject::Bool(_) | NSNumberHostObject::Char(_) => b"c".as_slice(),
        NSNumberHostObject::UnsignedLongLong(_) => b"Q".as_slice(),
        NSNumberHostObject::UnsignedInt(_) => b"I".as_slice(),
        NSNumberHostObject::Int(_) => b"i".as_slice(),
        NSNumberHostObject::LongLong(_) => b"q".as_slice(),
        NSNumberHostObject::Float(_) => b"f".as_slice(),
        NSNumberHostObject::Double(_) => b"d".as_slice(),
        NSNumberHostObject::Short(_) => b"s".as_slice(),
        NSNumberHostObject::UnsignedShort(_) => b"S".as_slice(),
    };
    env.mem.alloc_and_write_cstr(encoding).cast_const()
}

- (id)description {
    msg![env; this stringValue]
}

- (id)stringValue {
    msg![env; this descriptionWithLocale:nil]
}
- (id)descriptionWithLocale:(id)locale {
    assert_eq!(locale, nil); // TODO
    // TODO: do not alloc format strings each time
    let format = match env.objc.borrow(this) {
        NSNumberHostObject::Bool(_) | NSNumberHostObject::Char(_) | NSNumberHostObject::Int(_) => from_rust_string(env, "%i".to_string()),
        NSNumberHostObject::Double(_) => from_rust_string(env, "%0.16g".to_string()),
        NSNumberHostObject::Float(_) => from_rust_string(env, "%0.7g".to_string()),
        NSNumberHostObject::LongLong(_) => from_rust_string(env, "%lli".to_string()),
        NSNumberHostObject::Short(_) => from_rust_string(env, "%hi".to_string()),
        NSNumberHostObject::UnsignedInt(_) => from_rust_string(env, "%u".to_string()),
        NSNumberHostObject::UnsignedLongLong(_) => from_rust_string(env, "%llu".to_string()),
        NSNumberHostObject::UnsignedShort(_) => from_rust_string(env, "%hu".to_string()),
    };
    let ns_string_class = env.objc.get_known_class("NSString", &mut env.mem);
    let sel = env.objc.lookup_selector("stringWithFormat:").unwrap();
    // TODO: type info for host-to-host message calls with var-args
    let res = match env.objc.borrow(this) {
        NSNumberHostObject::Bool(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value as i32)),
        NSNumberHostObject::Char(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
        NSNumberHostObject::Double(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
        NSNumberHostObject::Float(value) => {
            // Need to promote float to double for the expected argument of %g
            crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value as f64))
        },
        NSNumberHostObject::Int(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
        NSNumberHostObject::LongLong(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
        NSNumberHostObject::Short(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
        NSNumberHostObject::UnsignedInt(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
        NSNumberHostObject::UnsignedLongLong(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
        NSNumberHostObject::UnsignedShort(value) => crate::objc::msg_send_no_type_checking(env, (ns_string_class, sel, format, *value)),
    };
    release(env, format);
    res
}

- (NSUInteger)hash {
    // The only requirement for [obj hash] is that values that compare equal
    // (via [obj isEqual] have the same hash. Hashing the underlying
    // bits works here.
    let value =
    match env.objc.borrow(this) {
        NSNumberHostObject::Bool(value) => *value as u64,
        NSNumberHostObject::UnsignedLongLong(value) => *value,
        NSNumberHostObject::UnsignedInt(value) => *value as u64,
        NSNumberHostObject::Int(value) => *value as u64,
        NSNumberHostObject::LongLong(value) => *value as u64,
        NSNumberHostObject::Float(value) => value.to_bits() as u64,
        NSNumberHostObject::Double(value) => value.to_bits(),
        NSNumberHostObject::Short(value) => *value as u64,
        NSNumberHostObject::UnsignedShort(value) => *value as u64,
        NSNumberHostObject::Char(value) => *value as u64,
    };
    super::hash_helper(&value)
}

- (bool)isEqual:(id)other {
    if this == other {
        return true;
    }
    let class: Class = msg_class![env; NSNumber class];
    if !msg![env; other isKindOfClass:class] {
        return false;
    }
    msg![env; this isEqualToNumber:other]
}

- (bool)isEqualToNumber:(id)other {
    let res: NSComparisonResult = msg![env; this compare:other];
    res == NSOrderedSame
}

- (NSComparisonResult)compare:(id)other { // NSNumber *
    let num = env.objc.borrow::<NSNumberHostObject>(this);
    let other_num = env.objc.borrow::<NSNumberHostObject>(other);
    let ordering = match (num.is_float(), other_num.is_float()) {
        (false, false) => num.as_i128().cmp(&other_num.as_i128()),
        // In case of having a float, we promote to double for comparison
        _ => {
            // TODO: handle partial cmp fails
            let res = num.as_double().partial_cmp(&other_num.as_double()).unwrap();
            if res == Ordering::Equal {
                // On ties, we compare as i128 as well
                num.as_i128().cmp(&other_num.as_i128())
            } else {
                res
            }
        },
    };
    from_rust_ordering(ordering)
}

// TODO: accessors etc

@end

};

pub fn is_conversion_lossless(env: &mut Environment, this: id, type_: CFNumberType) -> bool {
    let num = env.objc.borrow::<NSNumberHostObject>(this);
    let num2: id = match type_ {
        kCFNumberSInt32Type | kCFNumberIntType => {
            let val: i32 = num.as_int();
            msg_class![env; NSNumber numberWithInt:val]
        }
        kCFNumberFloat32Type | kCFNumberFloatType => {
            let val: f32 = num.as_float();
            msg_class![env; NSNumber numberWithFloat:val]
        }
        kCFNumberSInt16Type | kCFNumberShortType => {
            let val: i16 = num.as_short();
            msg_class![env; NSNumber numberWithShort:val]
        }
        kCFNumberSInt8Type | kCFNumberCharType => {
            let val: i8 = num.as_char();
            msg_class![env; NSNumber numberWithChar:val]
        }
        _ => unimplemented!("is_conversion_lossless for {}", type_),
    };
    msg![env; this isEqualToNumber:num2]
}

#[cfg(test)]
mod tests {
    use super::objc_type_size;

    #[test]
    fn computes_sizes_for_scalar_pointer_array_and_struct_encodings() {
        assert_eq!(objc_type_size(b"i"), Some(4));
        assert_eq!(objc_type_size(b"^v"), Some(4));
        assert_eq!(objc_type_size(b"[3{CGPoint=ff}]"), Some(24));
        assert_eq!(objc_type_size(b"{CGPoint=ff}"), Some(8));
        assert_eq!(
            objc_type_size(b"{CGRect={CGPoint=ff}{CGSize=ff}}"),
            Some(16)
        );
        assert_eq!(
            objc_type_size(b"{ccBezierConfig={CGPoint=ff}{CGPoint=ff}{CGPoint=ff}}"),
            Some(24)
        );
    }

    #[test]
    fn rejects_incomplete_or_trailing_type_encodings() {
        assert_eq!(objc_type_size(b"{CGPoint=ff"), None);
        assert_eq!(objc_type_size(b"i4"), None);
    }
}
