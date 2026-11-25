/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.app.AlertDialog;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.text.Editable;
import android.text.InputFilter;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.widget.*;
import java.util.Locale;

/** Appearance preferences are available even during the first IPA extraction. */
final class ZfAppearanceView extends ScrollView {
    private final ManagerActivity activity;
    private final ZfAppearance appearance;
    private final ZfAppearance.Palette colors;
    private final Runnable changed;

    ZfAppearanceView(ManagerActivity activity, ZfAppearance appearance, ZfAppearance.Palette colors,
                     Runnable changed, Runnable back) {
        super(activity);
        this.activity = activity;
        this.appearance = appearance;
        this.colors = colors;
        this.changed = changed;
        setFillViewport(true);

        LinearLayout content = column();
        content.setPadding(dp(6), dp(6), dp(6), dp(16));
        addView(content);
        LinearLayout header = new LinearLayout(activity);
        header.setGravity(Gravity.CENTER_VERTICAL);
        Button previous = control("‹", colors.surface, colors.ink, true);
        previous.setTextSize(26); previous.setContentDescription("返回"); previous.setOnClickListener(v -> back.run());
        header.addView(previous, new LinearLayout.LayoutParams(dp(48), dp(48)));
        TextView title = label("外观", 24, true);
        title.setPadding(dp(12), 0, 0, 0);
        header.addView(title);
        content.addView(header);

        content.addView(heading("主题"));
        LinearLayout modes = new LinearLayout(activity);
        modes.setPadding(dp(3), dp(3), dp(3), dp(3));
        modes.setBackground(shape(colors.soft, 10, false));
        String[] modesList = {ZfAppearance.LIGHT, ZfAppearance.DARK, ZfAppearance.SYSTEM};
        String[] modeLabels = {"浅色", "深色", "跟随系统"};
        for (int i = 0; i < modesList.length; i++) {
            String mode = modesList[i];
            boolean selected = mode.equals(appearance.mode);
            Button option = control(modeLabels[i], selected ? colors.surface : Color.TRANSPARENT,
                selected ? colors.accentText : colors.muted, false);
            option.setSelected(selected);
            if (selected) option.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            option.setOnClickListener(v -> {
                appearance.mode = mode;
                appearance.save();
                changed.run();
            });
            modes.addView(option, new LinearLayout.LayoutParams(0, -2, 1));
        }
        content.addView(modes);
        content.addView(heading("强调色"));

        for (int row = 0; row < 2; row++) {
            LinearLayout options = new LinearLayout(activity);
            for (int col = 0; col < 4; col++) {
                int i = 4 * row + col;
                int choice = i == ZfAppearance.COLORS.length ? ZfAppearance.CUSTOM : i;
                options.addView(swatch(choice), new LinearLayout.LayoutParams(0, -2, 1));
            }
            content.addView(options);
        }
        Button reset = control("恢复默认外观", colors.surface, colors.ink, true);
        reset.setPadding(dp(14), 0, dp(14), 0);
        reset.setOnClickListener(v -> { appearance.reset(); changed.run(); });
        LinearLayout.LayoutParams resetSize = new LinearLayout.LayoutParams(-2, -2);
        resetSize.topMargin = dp(18);
        content.addView(reset, resetSize);
    }

    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private LinearLayout column() {
        LinearLayout box = new LinearLayout(activity);
        box.setOrientation(LinearLayout.VERTICAL);
        return box;
    }
    private GradientDrawable shape(int fill, int radius, boolean outline) {
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(fill); bg.setCornerRadius(dp(radius));
        if (outline) bg.setStroke(dp(1), colors.line);
        return bg;
    }
    private RippleDrawable ripple(GradientDrawable bg) {
        return new RippleDrawable(ColorStateList.valueOf((colors.ink & 0x00ffffff) | 0x22000000),
            bg, shape(Color.WHITE, 7, false));
    }
    private Button control(String name, int fill, int ink, boolean outline) {
        Button b = new Button(activity);
        b.setText(name); b.setTextSize(15); b.setTextColor(ink); b.setAllCaps(false);
        b.setPadding(dp(2), 0, dp(2), 0);
        b.setMinWidth(0); b.setMinimumWidth(0); b.setMinHeight(dp(48)); b.setMinimumHeight(dp(48));
        b.setStateListAnimator(null);
        b.setBackground(ripple(shape(fill, 7, outline)));
        return b;
    }
    private TextView label(String text, int size, boolean bold) {
        TextView view = new TextView(activity);
        view.setText(text); view.setTextSize(size); view.setTextColor(colors.ink);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }
    private TextView heading(String name) {
        TextView text = label(name, 17, true);
        text.setPadding(0, dp(18), 0, dp(9));
        return text;
    }

    private LinearLayout swatch(int choice) {
        boolean custom = choice == ZfAppearance.CUSTOM;
        boolean active = choice == appearance.choice;
        String name = custom ? "自定义" : ZfAppearance.NAMES[choice];
        int fill = custom ? appearance.custom : ZfAppearance.COLORS[choice];
        LinearLayout tile = column();
        tile.setGravity(Gravity.CENTER);
        tile.setPadding(0, dp(6), 0, dp(7));
        tile.setBackground(ripple(shape(Color.TRANSPARENT, 7, false)));
        tile.setSelected(active); tile.setFocusable(true); tile.setContentDescription(name);
        FrameLayout circle = new FrameLayout(activity);
        if (active) {
            GradientDrawable ring = shape(Color.TRANSPARENT, 24, false);
            ring.setStroke(dp(2), colors.ink); circle.setBackground(ring);
        }
        TextView dot = label(active ? "✓" : custom ? "+" : "", 19, true);
        dot.setGravity(Gravity.CENTER); dot.setTextColor(ZfAppearance.foreground(fill));
        GradientDrawable disc = shape(fill, 20, false);
        disc.setStroke(dp(1), ZfAppearance.mix(fill, ZfAppearance.foreground(fill), 0.21));
        dot.setBackground(disc);
        circle.addView(dot, new FrameLayout.LayoutParams(dp(34), dp(34), Gravity.CENTER));
        tile.addView(circle, new LinearLayout.LayoutParams(dp(44), dp(44)));
        TextView nameLabel = label(name, 14, active);
        nameLabel.setTextColor(active ? colors.ink : colors.muted); nameLabel.setGravity(Gravity.CENTER);
        tile.addView(nameLabel);
        tile.setOnClickListener(v -> {
            if (custom) customDialog();
            else {
                appearance.choice = choice;
                appearance.save();
                changed.run();
            }
        });
        return tile;
    }

    private String hex(int color) { return String.format(Locale.ROOT, "#%06X", color & 0xffffff); }

    private void customDialog() {
        int current = appearance.custom;
        AlertDialog.Builder builder = new AlertDialog.Builder(activity, colors.dark
            ? android.R.style.Theme_Material_Dialog_Alert : android.R.style.Theme_Material_Light_Dialog_Alert);
        LinearLayout form = column();
        form.setPadding(dp(24), dp(8), dp(24), dp(8));
        LinearLayout sampleRow = new LinearLayout(activity); sampleRow.setGravity(Gravity.CENTER_VERTICAL);
        View sample = new View(activity); sample.setBackground(shape(current, 8, true));
        sampleRow.addView(sample, new LinearLayout.LayoutParams(dp(44), dp(44)));
        EditText field = new EditText(builder.getContext());
        field.setContentDescription("十六进制颜色"); field.setSingleLine(true);
        field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        field.setFilters(new InputFilter[]{new InputFilter.LengthFilter(7)});
        field.setText(hex(current)); field.setSelectAllOnFocus(true); field.setHint("#RRGGBB");
        field.setBackgroundTintList(ColorStateList.valueOf(colors.accentText));
        LinearLayout.LayoutParams fieldSize = new LinearLayout.LayoutParams(0, -2, 1);
        fieldSize.leftMargin = dp(12);
        sampleRow.addView(field, fieldSize); form.addView(sampleRow);
        int[] channels = {Color.red(current), Color.green(current), Color.blue(current)};
        String[] channelNames = {"红", "绿", "蓝"};
        SeekBar[] sliders = new SeekBar[3];
        for (int i = 0; i < channels.length; i++) {
            final int channel = i;
            LinearLayout row = new LinearLayout(activity); row.setGravity(Gravity.CENTER_VERTICAL);
            row.addView(label(channelNames[i], 14, false));
            SeekBar slider = new SeekBar(builder.getContext());
            slider.setContentDescription(channelNames[i]); slider.setMax(255); slider.setProgress(channels[i]);
            slider.setThumbTintList(ColorStateList.valueOf(colors.accentText));
            slider.setProgressTintList(ColorStateList.valueOf(colors.accentText));
            sliders[i] = slider;
            slider.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                public void onStartTrackingTouch(SeekBar s) {}
                public void onStopTrackingTouch(SeekBar s) {}
                public void onProgressChanged(SeekBar s, int value, boolean fromUser) {
                    if (fromUser) {
                        channels[channel] = value;
                        field.setText(hex(Color.rgb(channels[0], channels[1], channels[2])));
                    }
                }
            });
            row.addView(slider, new LinearLayout.LayoutParams(0, dp(48), 1));
            form.addView(row);
        }
        ScrollView scroll = new ScrollView(activity); scroll.addView(form);
        AlertDialog dialog = builder.setTitle("自定义强调色").setView(scroll)
            .setNegativeButton("取消", null).setPositiveButton("应用", (d, w) -> {
                appearance.choice = ZfAppearance.CUSTOM;
                appearance.custom = Color.rgb(channels[0], channels[1], channels[2]);
                appearance.save(); changed.run();
            }).show();
        activity.tintDialogButtons(dialog);
        field.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void afterTextChanged(Editable s) {}
            public void onTextChanged(CharSequence value, int start, int before, int count) {
                String digits = value.toString();
                boolean valid = digits.matches("#?[0-9a-fA-F]{6}");
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(valid);
                if (!valid) return;
                int color = Color.parseColor(digits.startsWith("#") ? digits : "#" + digits);
                channels[0] = Color.red(color); channels[1] = Color.green(color); channels[2] = Color.blue(color);
                for (int i = 0; i < channels.length; i++) sliders[i].setProgress(channels[i]);
                sample.setBackground(shape(color, 8, true));
            }
        });
    }
}
