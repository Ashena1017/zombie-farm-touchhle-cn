/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `UITextView`.

use crate::frameworks::core_graphics::cg_context::CGContextSetRGBFillColor;
use crate::frameworks::core_graphics::cg_geometry::CGRectZero;
use crate::frameworks::core_graphics::{CGFloat, CGPoint, CGRect, CGSize};
use crate::frameworks::foundation::ns_string::{get_static_str, to_rust_string};
use crate::frameworks::foundation::{NSRange, NSUInteger};
use crate::frameworks::uikit::ui_color;
use crate::frameworks::uikit::ui_font::{
    break_lines_with_font, size_with_font, UILineBreakModeWordWrap, UITextAlignment,
    UITextAlignmentLeft,
};
use crate::frameworks::uikit::ui_graphics::UIGraphicsGetCurrentContext;
use crate::frameworks::uikit::ui_view::ui_control::ui_text_field::UIReturnKeyType;
use crate::objc::{
    id, impl_HostObject_with_superclass, msg, msg_class, msg_super, nil, objc_classes, release,
    retain, todo_objc_setter, ClassExports, NSZonePtr,
};
use crate::Environment;

type UIDataDetectorTypes = NSUInteger;
const TEXT_INSET: CGFloat = 8.0;

pub struct UITextViewHostObject {
    superclass: super::UIScrollViewHostObject,
    editable: bool,
    /// `NSString*`
    text: id,
    /// `UIFont*`
    font: id,
    /// `UIColor*`
    text_color: id,
    text_alignment: UITextAlignment,
}
impl_HostObject_with_superclass!(UITextViewHostObject);
impl Default for UITextViewHostObject {
    fn default() -> Self {
        UITextViewHostObject {
            superclass: Default::default(),
            editable: false,
            font: nil,
            text: nil,
            text_color: nil,
            text_alignment: UITextAlignmentLeft,
        }
    }
}

fn text_layout_size(viewport: CGSize) -> CGSize {
    CGSize {
        width: (viewport.width - 2.0 * TEXT_INSET).max(0.0),
        height: (viewport.height - 2.0 * TEXT_INSET).max(0.0),
    }
}

// Update contentOffset and contentSize when anything that potentially affects
// contentSize like font and text change.
fn update_scroll(env: &mut Environment, this: id) {
    let bounds: CGRect = msg![env; this bounds];
    let bound_size = bounds.size;
    let font: id = msg![env; this font];
    let text: id = msg![env; this text];

    // Calculate our new contentSize
    let calculated_size = if text == nil || font == nil {
        CGSize { width: 0.0, height: 0.0 }
    } else {
        let text = to_rust_string(env, text);
        let layout_size = text_layout_size(bound_size);
        let size = size_with_font(env, font, &text, Some((layout_size, UILineBreakModeWordWrap)));
        CGSize {
            width: bound_size.width,
            height: size.height + 2.0 * TEXT_INSET,
        }
    };
    () = msg![env; this setContentSize:calculated_size];

    let offset: CGPoint = msg![env; this contentOffset];
    let clamped = CGPoint {
        x: offset.x.clamp(0.0, (calculated_size.width - bound_size.width).max(0.0)),
        y: offset.y.clamp(0.0, (calculated_size.height - bound_size.height).max(0.0)),
    };
    if offset != clamped {
        () = msg![env; this setContentOffset:clamped];
    }
}
pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation UITextView: UIScrollView

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::<UITextViewHostObject>::default();
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

- (id)initWithFrame:(CGRect)frame {
    let this: id = msg_super![env; this initWithFrame:frame];
    // TODO: refactor to a common init with `initWithCoder:`
    // These aren't redundant, the setters fetch the real defaults.
    () = msg![env; this setFont:nil];
    () = msg![env; this setTextColor:nil];
    this
}

- (id)initWithCoder:(id)coder {
    let this: id = msg_super![env; this initWithCoder:coder];
    () = msg![env; this setFont:nil];

    let text_key = get_static_str(env, "UIText");
    let text: id = msg![env; coder decodeObjectForKey:text_key];
    () = msg![env; this setText:text];
    let color_key = get_static_str(env, "UITextColor");
    let color: id = msg![env; coder decodeObjectForKey:color_key];
    () = msg![env; this setTextColor:color];
    let alignment_key = get_static_str(env, "UITextAlignment");
    let alignment: UITextAlignment = msg![env; coder decodeIntForKey:alignment_key];
    () = msg![env; this setTextAlignment:alignment];
    let editable_key = get_static_str(env, "UIEditable");
    let editable: bool = msg![env; coder decodeBoolForKey:editable_key];
    () = msg![env; this setEditable:editable];
    this
}

- (())dealloc {
    let UITextViewHostObject {
        superclass: _,
        editable: _,
        font,
        text,
        text_color,
        text_alignment: _
    } = std::mem::take(env.objc.borrow_mut(this));

    release(env, font);
    release(env, text_color);
    release(env, text);
    msg_super![env; this dealloc]
}

- (id)text {
    env.objc.borrow::<UITextViewHostObject>(this).text
}
- (())setText:(id)new_text { // NSString*
    let hostobj  = env.objc.borrow_mut::<UITextViewHostObject>(this);
    let old_text = std::mem::replace(&mut hostobj.text, new_text);
    retain(env, new_text);
    release(env, old_text);
    update_scroll(env,this);
    () = msg![env; this setNeedsDisplay];
}

- (id)textColor {
    env.objc.borrow::<UITextViewHostObject>(this).text_color
}
- (())setTextColor:(id)new_text_color { // UIColor*
    let new_text_color: id = if new_text_color == nil {
        msg_class![env; UIColor blackColor]
    } else {
        new_text_color
    };

    let hostobj  = env.objc.borrow_mut::<UITextViewHostObject>(this);
    let old_text_color = std::mem::replace(&mut hostobj.text_color, new_text_color);
    retain(env, new_text_color);
    release(env, old_text_color);
    () = msg![env; this setNeedsDisplay];
}

- (UITextAlignment)textAlignment {
    env.objc.borrow::<UITextViewHostObject>(this).text_alignment
}
- (())setTextAlignment:(UITextAlignment)new_text_alignment {
    env.objc.borrow_mut::<UITextViewHostObject>(this).text_alignment = new_text_alignment;
    () = msg![env; this setNeedsDisplay];
}

- (id)font {
    env.objc.borrow::<UITextViewHostObject>(this).font
}
- (())setFont:(id)new_font { // UIFont*
    let new_font: id = if new_font == nil {
        // reset to default
        let size: CGFloat = 17.0;
        msg_class![env; UIFont systemFontOfSize:size]
    } else {
        new_font
    };

    let hostobj  = env.objc.borrow_mut::<UITextViewHostObject>(this);
    let old_font = std::mem::replace(&mut hostobj.font, new_font);
    retain(env, new_font);
    release(env, old_font);
    update_scroll(env,this);
    () = msg![env; this setNeedsDisplay];
}

- (())flashScrollIndicators {
    // TODO
}

// TODO: Make editable actually do something
- (bool)isEditable {
    env.objc.borrow::<UITextViewHostObject>(this).editable
}
- (())setEditable:(bool)editable {
    env.objc.borrow_mut::<UITextViewHostObject>(this).editable = editable;
}

- (())scrollRangeToVisible:(NSRange)range {
    let &mut UITextViewHostObject {
        font,
        text,
        ..
    } = env.objc.borrow_mut(this);

    if text == nil || font == nil || range.location > msg![env; text length] {
        return;
    }

    let bounds: CGRect = msg![env; this bounds];
    let bound_size = bounds.size;

    let text = to_rust_string(env, text);

    let layout_size = text_layout_size(bound_size);
    let lines = break_lines_with_font(env, font, &text, Some((layout_size, UILineBreakModeWordWrap)));

    let mut line_count = 0;
    let mut current_position = 0;

    for (_, line) in lines {
        current_position += line.len();

        if let Some(offset) = text[current_position..].find(|c: char| !c.is_whitespace()) {
            current_position += offset;
        } else {
            current_position = text.len();
        }

        if range.location <= current_position as u32 {
            break;
        }

        line_count += 1;
    }

    let line_height: CGFloat = msg![env; font lineHeight];
    let leading: CGFloat = msg![env; font leading];

    let height_to_range_start = TEXT_INSET + (line_count + 1) as f32 * line_height - leading;

    let content_offset: CGPoint = msg![env; this contentOffset];

    if height_to_range_start - line_height < content_offset.y {
        let new_scroll_y = CGPoint {x: 0.0, y: TEXT_INSET + line_count as f32 * line_height};
        () = msg![env; this setContentOffset:new_scroll_y];
    }
    else if height_to_range_start > content_offset.y + bound_size.height {
        let new_scroll_y = CGPoint {x: 0.0, y: height_to_range_start- bound_size.height};
        () = msg![env; this setContentOffset:new_scroll_y];
    }

    update_scroll(env, this);
}

- (())setReturnKeyType:(UIReturnKeyType)type_ {
    todo_objc_setter!(this, type_);
}

- (())setDataDetectorTypes:(UIDataDetectorTypes)types {
    todo_objc_setter!(this, types);
}

- (())drawRect:(CGRect)_rect {
    let bounds: CGRect = msg![env; this bounds];
    let context = UIGraphicsGetCurrentContext(env);

    let &mut UITextViewHostObject {
        superclass: _,
        editable: _,
        font,
        text,
        text_color,
        text_alignment
    } = env.objc.borrow_mut(this);

    let (r, g, b, a) = ui_color::get_rgba(&env.objc, text_color);
    CGContextSetRGBFillColor(env, context, r, g, b, a);

    let rect = CGRect {
        origin: CGPoint { x: TEXT_INSET, y: TEXT_INSET },
        // Drawing is in content coordinates. Extend the text rect to the
        // bottom of the visible area after scrolling.
        size: CGSize {
            width: text_layout_size(bounds.size).width,
            height: bounds.size.height + bounds.origin.y - TEXT_INSET,
        }
    };

    log_dbg!("UItextView text rendering in rect {:?}", rect);
    let _size: CGSize = msg![env; text drawInRect:rect
                                         withFont:font
                                    lineBreakMode:UILineBreakModeWordWrap
                                        alignment:text_alignment];
}

@end

// Legacy text views can archive a private selection overlay without geometry.
// Keep it inert until text selection itself is implemented.
@implementation UITextSelectionView: UIView

- (id)initWithCoder:(id)_coder {
    let this: id = msg![env; this initWithFrame:CGRectZero];
    () = msg![env; this setUserInteractionEnabled:false];
    this
}

@end

};
