/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.touchhle.android;

import android.app.*;
import android.content.*;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;

/** Native touch-first launcher; the emulator runs in the separate :game process. */
public class ManagerActivity extends Activity {
    private static final int IMPORT_IPA = 10, IMPORT_SAVE = 11, EXPORT_SAVE = 12;
    private int INK, NIGHT_BLUE, LAVENDER, MUTED, BACKGROUND, SOFT, LINE, GOLD, SURFACE;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private ZfStorage storage;
    private List<ZfIpa> versions = new ArrayList<>();
    private List<File> backups = new ArrayList<>();
    private ZfIpa selected;
    private JSONObject settings = new JSONObject();
    private ZfSave currency;
    private String saveMessage = "还没有存档，请先进入游戏";
    private boolean busy, running;
    private int page;
    private LinearLayout shell, body;
    private Spinner family, scale, fps;
    private EditText customScale, customFps;
    private Switch fix;
    private TextView resolution;
    private String pendingId;
    private File exportFile;
    private boolean nightMode;
    private final Handler statusHandler = new Handler(Looper.getMainLooper());
    private final Handler settingsHandler = new Handler(Looper.getMainLooper());
    private Runnable settingsSaveRequest;
    private TextView settingsStatus;
    private final Runnable statusCheck = new Runnable() {
        @Override public void run() {
            // Resume can precede the game process releasing its lease on exit.
            if (storage != null && !busy && running != storage.gameRunning()) refresh(false);
            statusHandler.postDelayed(this, 1000);
        }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (state != null) {
            page = state.getInt("page", 0); pendingId = state.getString("pendingId");
            String path = state.getString("exportFile"); if (path != null) exportFile = new File(path);
        }
        nightMode = getPreferences(MODE_PRIVATE).getBoolean("night_mode", false);
        applyPalette();
        try { storage = new ZfStorage(this); }
        catch (Exception e) { error(e); return; }
        setTitle("ZF游戏管理"); render();
    }
    @Override protected void onResume() {
        super.onResume(); if (storage != null && !busy) refresh(true);
        statusHandler.removeCallbacks(statusCheck); statusHandler.postDelayed(statusCheck, 1000);
    }
    @Override protected void onPause() { statusHandler.removeCallbacks(statusCheck); super.onPause(); }
    @Override protected void onSaveInstanceState(Bundle state) {
        state.putInt("page", page); state.putString("pendingId", pendingId);
        if (exportFile != null) state.putString("exportFile", exportFile.getPath());
        super.onSaveInstanceState(state);
    }
    @Override protected void onDestroy() {
        statusHandler.removeCallbacks(statusCheck);
        settingsHandler.removeCallbacksAndMessages(null);
        worker.shutdown(); super.onDestroy();
    }

    private void applyPalette() {
        if (nightMode) {
            INK = Color.rgb(232, 237, 234); NIGHT_BLUE = Color.rgb(76, 139, 111);
            LAVENDER = Color.rgb(126, 177, 146); MUTED = Color.rgb(165, 179, 173);
            BACKGROUND = Color.rgb(29, 35, 38); SURFACE = Color.rgb(38, 46, 48);
            SOFT = Color.rgb(48, 65, 56); LINE = Color.rgb(62, 75, 69);
            GOLD = Color.rgb(214, 168, 99);
        } else {
            INK = Color.rgb(38, 52, 58); NIGHT_BLUE = Color.rgb(45, 101, 87);
            LAVENDER = Color.rgb(111, 148, 127); MUTED = Color.rgb(105, 122, 120);
            BACKGROUND = Color.rgb(243, 246, 244); SURFACE = Color.WHITE;
            SOFT = Color.rgb(228, 236, 231); LINE = Color.rgb(220, 228, 223);
            GOLD = Color.rgb(214, 160, 82);
        }
        getWindow().setStatusBarColor(NIGHT_BLUE);
        getWindow().setNavigationBarColor(nightMode ? Color.rgb(22, 27, 30) : Color.rgb(36, 83, 71));
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            int flags = getWindow().getDecorView().getSystemUiVisibility();
            flags &= ~(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
            getWindow().getDecorView().setSystemUiVisibility(flags);
        }
    }

    private interface Task { String run() throws Exception; }
    private void task(Task action) { task(action, null); }
    private void task(Task action, Runnable after) {
        if (busy) return;
        busy = true; render();
        worker.execute(() -> {
            String message = null; Exception failure = null;
            try (ZfStorage.Lease ignored = storage.lock()) { message = action.run(); }
            catch (Exception e) { failure = e; }
            final String result = message; final Exception problem = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                busy = false;
                if (problem != null) error(problem); else if (result != null) toast(result);
                if (problem == null && after != null) after.run();
                refresh(false);
            });
        });
    }
    private void refresh(boolean install) {
        if (busy) return;
        busy = true; render();
        worker.execute(() -> {
            Exception failure = null;
            try {
                if (install && !storage.gameRunning()) {
                    try (ZfStorage.Lease ignored = storage.lock()) { storage.ensureBundled(); }
                }
                versions = storage.versions(); selected = storage.selected(); settings = storage.settings(selected.appId);
                running = storage.gameRunning(); currency = null;
                if (!running) {
                    try { currency = storage.currency(selected.appId); saveMessage = "当前存档已校验"; }
                    catch (Exception e) { saveMessage = storage.live(selected.appId).exists() ? e.getMessage() : "还没有存档，请先进入游戏"; }
                } else saveMessage = "游戏运行中，退出后可管理存档";
                backups = storage.backups(selected.appId);
            } catch (Exception e) { failure = e; }
            final Exception problem = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                busy = false; render(); if (problem != null) error(problem);
            });
        });
    }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setPadding(0, dp(4), 0, dp(4)); return view;
    }
    private LinearLayout vertical() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    private LinearLayout row() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.HORIZONTAL); v.setGravity(Gravity.CENTER_VERTICAL); return v; }
    private GradientDrawable shape(int color, int radius) {
        GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); return d;
    }
    private Button button(String title, boolean primary, Runnable action) {
        Button b = new Button(this); b.setText(title); b.setAllCaps(false); b.setTextSize(15);
        b.setTextColor(primary ? Color.WHITE : NIGHT_BLUE);
        b.setBackground(shape(primary ? NIGHT_BLUE : SOFT, 6));
        b.setMinHeight(dp(48)); b.setStateListAnimator(null);
        b.setOnClickListener(v -> action.run()); return b;
    }
    private void addButton(LinearLayout parent, Button button) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, dp(52)); p.topMargin = dp(6); parent.addView(button, p);
    }
    private void pair(LinearLayout parent, View first, View second) {
        LinearLayout r = row(); LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -2, 1); p.setMargins(0, 0, dp(8), 0);
        r.addView(first, p); r.addView(second, new LinearLayout.LayoutParams(0, -2, 1)); parent.addView(r);
    }
    private LinearLayout card(String title, String subtitle) {
        LinearLayout card = vertical(); card.setPadding(dp(16), dp(13), dp(16), dp(14));
        GradientDrawable surface = shape(SURFACE, 6); surface.setStroke(dp(1), LINE); card.setBackground(surface);
        card.addView(text(title, 17, INK, true));
        if (subtitle != null) card.addView(text(subtitle, 13, MUTED, false));
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.bottomMargin = dp(10); body.addView(card, p);
        return card;
    }
    private boolean editable() { return !busy && !running && selected != null; }
    private void render() {
        shell = vertical(); shell.setBackgroundColor(BACKGROUND); shell.setPadding(dp(14), dp(12), dp(14), 0);
        FrameLayout hero = new FrameLayout(this); hero.setBackground(shape(SOFT, 8)); hero.setClipToOutline(true);
        LinearLayout titles = vertical(); titles.setPadding(dp(17), dp(17), 0, 0);
        titles.addView(text("ZF游戏管理", 24, INK, true));
        titles.addView(text("僵尸农场 · 中文版", 12, MUTED, false));
        FrameLayout.LayoutParams titleParams = new FrameLayout.LayoutParams(-1, -1, Gravity.TOP | Gravity.LEFT);
        hero.addView(titles, titleParams);
        View accent = new View(this); accent.setBackgroundColor(GOLD);
        FrameLayout.LayoutParams accentParams = new FrameLayout.LayoutParams(dp(36), dp(2), Gravity.LEFT | Gravity.BOTTOM);
        accentParams.setMargins(dp(17), 0, 0, dp(13)); hero.addView(accent, accentParams);
        TextView state = text(busy ? "处理中…" : running ? "游戏运行中" : "准备就绪", 11, NIGHT_BLUE, true);
        state.setPadding(dp(9), dp(4), dp(9), dp(4)); state.setBackground(shape(SURFACE, 12));
        FrameLayout.LayoutParams stateParams = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP | Gravity.RIGHT);
        stateParams.setMargins(0, dp(10), dp(58), 0); hero.addView(state, stateParams);
        Button themeButton = new Button(this);
        themeButton.setText(nightMode ? "☾" : "☀"); themeButton.setTextSize(21);
        themeButton.setTextColor(NIGHT_BLUE); themeButton.setContentDescription(nightMode ? "切换到日间模式" : "切换到夜间模式");
        themeButton.setPadding(0, 0, 0, 0); themeButton.setMinWidth(dp(40)); themeButton.setMinimumWidth(dp(40));
        themeButton.setMinHeight(dp(40)); themeButton.setMinimumHeight(dp(40)); themeButton.setStateListAnimator(null);
        GradientDrawable themeBg = shape(SURFACE, 8); themeBg.setStroke(dp(1), LINE); themeButton.setBackground(themeBg);
        FrameLayout.LayoutParams themeParams = new FrameLayout.LayoutParams(dp(40), dp(40), Gravity.TOP | Gravity.RIGHT);
        themeParams.setMargins(0, dp(52), dp(10), 0); hero.addView(themeButton, themeParams);
        themeButton.setOnClickListener(v -> {
            flushSettingsSave();
            nightMode = !nightMode; getPreferences(MODE_PRIVATE).edit().putBoolean("night_mode", nightMode).apply();
            applyPalette(); render();
        });
        LinearLayout.LayoutParams heroParams = new LinearLayout.LayoutParams(-1, dp(142)); heroParams.bottomMargin = dp(10);
        shell.addView(hero, heroParams);
        LinearLayout nav = row(); nav.setPadding(dp(4), dp(3), dp(4), dp(3));
        GradientDrawable navBg = shape(SURFACE, 7); navBg.setStroke(dp(1), LINE); nav.setBackground(navBg);
        String[] tabs = {"游戏", "设置", "存档"};
        for (int i = 0; i < tabs.length; i++) {
            final int index = i; Button b = new Button(this); b.setText(tabs[i]); b.setAllCaps(false); b.setTextSize(14);
            b.setTextColor(page == i ? Color.WHITE : MUTED); b.setBackground(shape(page == i ? NIGHT_BLUE : Color.TRANSPARENT, 5));
            b.setMinHeight(0); b.setMinimumHeight(dp(42)); b.setPadding(dp(4), 0, dp(4), 0); b.setStateListAnimator(null);
            b.setOnClickListener(v -> { page = index; render(); }); b.setEnabled(!busy);
            LinearLayout.LayoutParams tabParams = new LinearLayout.LayoutParams(0, dp(42), 1);
            tabParams.setMargins(dp(2), 0, dp(2), 0); nav.addView(b, tabParams);
        }
        LinearLayout.LayoutParams navParams = new LinearLayout.LayoutParams(-1, -2); navParams.bottomMargin = dp(4); shell.addView(nav, navParams);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        body = vertical(); body.setPadding(0, dp(8), 0, dp(18)); scroll.addView(body);
        shell.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1)); setContentView(shell);
        if (selected == null) { card("正在准备游戏", "首次打开会安装内置中文版，请稍候。"); return; }
        if (page == 0) gamePage(); else if (page == 1) settingsPage(); else savePage();
    }
    private Spinner spinner(String[] values) {
        Spinner s = new Spinner(this); ArrayAdapter<String> adapter = new ArrayAdapter<String>(this, android.R.layout.simple_spinner_item, values) {
            @Override public View getView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getView(position, convertView, parent); v.setTextColor(INK); return v;
            }
            @Override public View getDropDownView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getDropDownView(position, convertView, parent);
                v.setTextColor(INK); v.setBackgroundColor(SURFACE); return v;
            }
        };
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); s.setAdapter(adapter); s.setMinimumHeight(dp(48));
        s.setBackgroundTintList(ColorStateList.valueOf(LINE));
        s.setEnabled(editable()); return s;
    }
    private EditText number(String hint, String value, boolean decimal) {
        EditText e = new EditText(this); e.setTextSize(16); e.setSingleLine(true); e.setHint(hint); e.setText(value);
        e.setInputType(decimal ? InputType.TYPE_CLASS_TEXT : InputType.TYPE_CLASS_NUMBER);
        e.setTextColor(INK); e.setHintTextColor(MUTED); e.setBackgroundTintList(ColorStateList.valueOf(LINE));
        e.setEnabled(editable()); return e;
    }
    private void gamePage() {
        LinearLayout version = card("游戏版本", "内置最新中文修复版，也可导入其他版本。");
        Spinner picker = new Spinner(this); ArrayAdapter<ZfIpa> adapter = new ArrayAdapter<ZfIpa>(this, android.R.layout.simple_spinner_item, versions) {
            @Override public View getView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getView(position, convertView, parent); v.setTextColor(INK); return v;
            }
            @Override public View getDropDownView(int position, View convertView, android.view.ViewGroup parent) {
                TextView v = (TextView)super.getDropDownView(position, convertView, parent);
                v.setTextColor(INK); v.setBackgroundColor(SURFACE); return v;
            }
        };
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); picker.setAdapter(adapter); picker.setMinimumHeight(dp(48));
        picker.setBackgroundTintList(ColorStateList.valueOf(LINE));
        int current = 0; for (int i = 0; i < versions.size(); i++) if (versions.get(i).file.equals(selected.file)) current = i;
        picker.setSelection(current); picker.setEnabled(editable()); version.addView(picker);
        picker.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> p) {}
            public void onItemSelected(AdapterView<?> p, View v, int pos, long id) {
                ZfIpa choice = versions.get(pos);
                if (!choice.file.equals(selected.file)) task(() -> { storage.select(choice); return "已切换游戏版本"; });
            }
        });
        version.addView(text("游戏版本 " + selected.version + " · " + String.format(Locale.ROOT, "%.1f MB", selected.file.length() / 1048576.0), 12, MUTED, false));
        Button importButton = button("导入 IPA", false, () -> chooseFile(IMPORT_IPA)); importButton.setEnabled(editable()); addButton(version, importButton);
        LinearLayout launch = card("开始游戏", "累计跳过 " + duration(settings.optLong("offset", 0)));
        if (running) {
            addButton(launch, button("返回正在运行的游戏", true, () -> startActivity(new Intent(this, MainActivity.class))));
            addButton(launch, button("退出游戏并返回管理器", false, () -> startActivity(new Intent(this, MainActivity.class)
                .putExtra("stop_game", true).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP))));
        } else {
            Button start = button("启动游戏", true, () -> launch(0)); start.setEnabled(editable()); addButton(launch, start);
            Button skip = button("启动并跳过时间", false, this::skipDialog); skip.setEnabled(editable()); addButton(launch, skip);
            if (settings.optLong("offset", 0) > 0) {
                Button reset = button("重置累计跳过时间", false, () -> new AlertDialog.Builder(this)
                    .setTitle("重置累计时间？")
                    .setMessage("只清除未来启动时使用的累计偏移，不会倒退或改写现有游戏进度。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("重置", (dialog, which) -> {
                        String id = selected.appId;
                        task(() -> { JSONObject app = new JSONObject(settings.toString()).put("offset", 0); storage.settings(id, app); return "累计跳过时间已重置"; });
                    }).show());
                reset.setEnabled(editable()); addButton(launch, reset);
            }
        }
        LinearLayout money = card("金币与脑子", saveMessage);
        EditText gold = number("金币", currency == null ? "" : Integer.toString(currency.gold), false);
        EditText brains = number("脑子", currency == null ? "" : Integer.toString(currency.brains), false);
        LinearLayout left = vertical(), right = vertical(); left.addView(text("金币", 13, MUTED, false)); left.addView(gold);
        right.addView(text("脑子", 13, MUTED, false)); right.addView(brains); pair(money, left, right);
        Button apply = button("保存货币修改", false, () -> {
            try {
                int g = Integer.parseInt(gold.getText().toString()), b = Integer.parseInt(brains.getText().toString()); String id = selected.appId;
                task(() -> { storage.setCurrency(id, g, b); return "货币已保存，原存档已自动备份"; });
            } catch (Exception e) { error(new IllegalArgumentException("请填写 0～2147483647 的整数")); }
        });
        apply.setEnabled(editable() && currency != null); addButton(money, apply);
        money.addView(text("每次修改前自动备份，可在“存档”页恢复。", 12, MUTED, false));
    }
    private String duration(long seconds) { return (seconds / 3600) + " 小时 " + ((seconds / 60) % 60) + " 分钟"; }
    private void launch(long seconds) {
        String id = selected.appId;
        task(() -> {
            storage.advance(id, seconds);
            return null;
        }, () -> startActivity(new Intent(this, MainActivity.class)));
    }
    private void skipDialog() {
        LinearLayout content = vertical(); content.setPadding(dp(24), dp(8), dp(24), dp(8));
        EditText hours = number("小时", settings.optString("skipHours", "6"), false);
        EditText minutes = number("分钟", settings.optString("skipMinutes", "0"), false);
        pair(content, hours, minutes); content.addView(text("跳过时间会累加，普通启动继续使用累计值。", 13, MUTED, false));
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("启动并跳过时间").setView(content)
            .setNegativeButton("取消", null).setPositiveButton("启动", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(-1).setOnClickListener(v -> {
            try {
                long h = Long.parseLong(hours.getText().toString()); int m = Integer.parseInt(minutes.getText().toString());
                if (h < 0 || h > 100000 || m < 0 || m > 59 || h * 3600 + m * 60 == 0) throw new IllegalArgumentException();
                String id = selected.appId; long seconds = h * 3600 + m * 60;
                JSONObject app = new JSONObject(settings.toString()).put("skipHours", h).put("skipMinutes", m);
                dialog.dismiss(); task(() -> {
                    storage.settings(id, app); storage.advance(id, seconds);
                    return null;
                }, () -> startActivity(new Intent(this, MainActivity.class)));
            } catch (Exception e) { toast("请输入小时与 0～59 的分钟，时间需大于零"); }
        })); dialog.show();
    }
    private void settingsPage() {
        LinearLayout display = card("画面设置", "按当前版本记忆设置；游戏画面保持比例并适配屏幕。");
        display.addView(text("设备类型", 13, MUTED, false)); family = spinner(new String[]{"iPhone（推荐）", "iPad"});
        family.setSelection(settings.optString("family", "iphone").equals("ipad") ? 1 : 0); display.addView(family); family.setEnabled(editable());
        display.addView(text("渲染倍率", 13, MUTED, false));
        scale = spinner(new String[]{"×1", "×1.25", "×1.5", "×1.75", "×2", "自定义"});
        String[] values = {"1", "1.25", "1.5", "1.75", "2"}; String current = settings.optString("scale", "1");
        int index = Arrays.asList(values).indexOf(current); scale.setSelection(index < 0 ? 5 : index); display.addView(scale); scale.setEnabled(editable());
        customScale = number("小数或分数，例如 1.5、3/2", current, true); display.addView(customScale);
        customScale.setVisibility(index < 0 ? View.VISIBLE : View.GONE); customScale.setEnabled(editable());
        resolution = text("", 13, LAVENDER, true); display.addView(resolution);
        AdapterView.OnItemSelectedListener sizes = new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> p) {}
            public void onItemSelected(AdapterView<?> p, View v, int position, long id) {
                customScale.setVisibility(scale.getSelectedItemPosition() == 5 ? View.VISIBLE : View.GONE);
                updateResolution(); queueSettingsSave();
            }
        }; family.setOnItemSelectedListener(sizes); scale.setOnItemSelectedListener(sizes);
        customScale.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int c, int n) {}
            public void onTextChanged(CharSequence s, int a, int b, int c) { updateResolution(); queueSettingsSave(); }
            public void afterTextChanged(android.text.Editable e) {}
        }); updateResolution();
        display.addView(text("Android 默认 iPhone ×1。较高倍率增加渲染负担；两指缩放由游戏处理。", 12, MUTED, false));
        LinearLayout timing = card("帧率设置", null);
        fps = spinner(new String[]{"30 FPS", "60 FPS（推荐）", "90 FPS", "120 FPS", "不限帧率", "自定义"});
        String[] rates = {"30", "60", "90", "120", "off"}; current = settings.optString("fps", "60");
        index = Arrays.asList(rates).indexOf(current); fps.setSelection(index < 0 ? 5 : index); timing.addView(fps); fps.setEnabled(editable());
        customFps = number("1～1000 FPS", current.equals("off") ? "60" : current, false); timing.addView(customFps);
        customFps.setVisibility(index < 0 ? View.VISIBLE : View.GONE); customFps.setEnabled(editable());
        fps.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            public void onNothingSelected(AdapterView<?> p) {}
            public void onItemSelected(AdapterView<?> p, View v, int position, long id) {
                customFps.setVisibility(position == 5 ? View.VISIBLE : View.GONE);
                queueSettingsSave();
            }
        });
        customFps.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int c, int n) {}
            public void onTextChanged(CharSequence s, int a, int b, int c) { queueSettingsSave(); }
            public void afterTextChanged(android.text.Editable e) {}
        });
        fix = new Switch(this); fix.setText("高速帧率修复（推荐开启）"); fix.setTextSize(14);
        fix.setThumbTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}}, new int[]{NIGHT_BLUE, Color.rgb(177, 174, 188)}));
        fix.setTrackTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}}, new int[]{0x6634415F, 0x55777786}));
        fix.setChecked(settings.optBoolean("fix", true)); fix.setEnabled(editable()); fix.setPadding(0, dp(14), 0, dp(8)); timing.addView(fix);
        fix.setOnCheckedChangeListener((button, checked) -> queueSettingsSave());
        timing.addView(text("关闭修复可能让游戏无法达到设定帧率。提高帧率不会加快游戏时间。", 12, MUTED, false));
        settingsStatus = text("已保存 · 下次启动生效", 12, LAVENDER, false); timing.addView(settingsStatus);
    }
    private void queueSettingsSave() {
        if (busy || selected == null || running || family == null || scale == null || fps == null || fix == null) return;
        if (settingsSaveRequest != null) settingsHandler.removeCallbacks(settingsSaveRequest);
        settingsSaveRequest = this::saveSettingsFromControls;
        settingsHandler.postDelayed(settingsSaveRequest, 250);
    }
    private void flushSettingsSave() {
        if (settingsSaveRequest == null) return;
        settingsHandler.removeCallbacks(settingsSaveRequest); settingsSaveRequest = null;
        saveSettingsFromControls();
    }
    private void saveSettingsFromControls() {
        settingsSaveRequest = null;
        if (isFinishing() || isDestroyed() || selected == null || family == null || scale == null || fps == null || fix == null) return;
        if (busy) {
            settingsSaveRequest = this::saveSettingsFromControls;
            settingsHandler.postDelayed(settingsSaveRequest, 120);
            return;
        }
        final JSONObject app;
        final String id = selected.appId;
        try {
            String scaleText = scaleValue(), fpsText = fpsValue();
            ZfStorage.scale(scaleText);
            if (!fpsText.equals("off")) {
                if (!fpsText.matches("[0-9]+")) throw new IllegalArgumentException("请输入 1～1000 的整数帧率");
                int rate = Integer.parseInt(fpsText);
                if (rate < 1 || rate > 1000) throw new IllegalArgumentException("请输入 1～1000 的整数帧率");
            }
            app = new JSONObject(settings.toString())
                .put("family", family.getSelectedItemPosition() == 1 ? "ipad" : "iphone")
                .put("scale", scaleText).put("fps", fpsText).put("fix", fix.isChecked());
            if (app.optString("family").equals(settings.optString("family", "iphone"))
                    && app.optString("scale").equals(settings.optString("scale", "1"))
                    && app.optString("fps").equals(settings.optString("fps", "60"))
                    && app.optBoolean("fix", true) == settings.optBoolean("fix", true)) return;
        } catch (Exception e) {
            if (settingsStatus != null) settingsStatus.setText("输入值尚未有效，因此未保存");
            return;
        }

        settings = app;
        busy = true;
        if (settingsStatus != null) settingsStatus.setText("正在保存…");
        worker.execute(() -> {
            Exception failure = null;
            try (ZfStorage.Lease ignored = storage.lock()) { storage.settings(id, app); }
            catch (Exception e) { failure = e; }
            final Exception problem = failure;
            runOnUiThread(() -> {
                if (isFinishing() || isDestroyed()) return;
                busy = false;
                if (problem == null) {
                    if (settingsStatus != null) settingsStatus.setText("已保存 · 下次启动生效");
                } else {
                    if (settingsStatus != null) settingsStatus.setText("保存失败");
                    error(problem);
                }
            });
        });
    }
    private String scaleValue() { String[] v = {"1", "1.25", "1.5", "1.75", "2"}; return scale.getSelectedItemPosition() == 5 ? customScale.getText().toString().trim() : v[scale.getSelectedItemPosition()]; }
    private String fpsValue() { String[] v = {"30", "60", "90", "120", "off"}; return fps.getSelectedItemPosition() == 5 ? customFps.getText().toString().trim() : v[fps.getSelectedItemPosition()]; }
    private void updateResolution() {
        try {
            double factor = ZfStorage.scale(scaleValue()); boolean ipad = family.getSelectedItemPosition() == 1;
            resolution.setText("渲染尺寸 " + Math.round((ipad ? 1024 : 480) * factor) + " × " + Math.round((ipad ? 768 : 320) * factor));
        } catch (Exception e) { resolution.setText("请输入有效倍率"); }
    }
    private void savePage() {
        LinearLayout current = card("当前存档", selected.name);
        current.addView(text(currency == null ? saveMessage : "金币 " + currency.gold + " · 脑子 " + currency.brains, 15, INK, true));
        current.addView(text("累计跳过 " + duration(settings.optLong("offset", 0)), 13, MUTED, false));
        Button backup = button("新建完整备份", true, () -> { String id = selected.appId; task(() -> { storage.backup(id, "手动"); return "完整备份已创建"; }); });
        backup.setEnabled(editable() && currency != null); addButton(current, backup);
        Button importButton = button("导入存档或备份", false, () -> { pendingId = selected.appId; chooseFile(IMPORT_SAVE); });
        importButton.setEnabled(editable()); addButton(current, importButton);
        current.addView(text("支持 ZF 完整备份 .zip 和 saveGame.bin2。完整备份包含进度、资料和累计跳过时间。", 12, MUTED, false));
        LinearLayout list = card("备份记录", backups.isEmpty() ? "尚无备份。修改货币和恢复进度前会自动备份。" : "点击记录可恢复、导出或删除。");
        for (File file : backups) {
            String title = file.getName().replaceFirst("_[^_]+\\.zip$", "");
            Button item = button(title, false, () -> backupActions(file)); item.setEnabled(!busy); addButton(list, item);
        }
    }
    private void backupActions(File file) {
        String id = selected.appId;
        new AlertDialog.Builder(this).setTitle("存档备份").setItems(new String[]{"恢复这份备份", "导出到手机文件", "删除这份备份"}, (d, which) -> {
            if (which == 0) {
                if (!editable()) { toast("请先退出游戏"); return; }
                new AlertDialog.Builder(this).setTitle("恢复备份？").setMessage("将恢复进度和累计跳过时间。当前进度会先自动备份。")
                    .setNegativeButton("取消", null).setPositiveButton("恢复", (a, b) -> task(() -> {
                        try (InputStream in = new FileInputStream(file)) { storage.restore(id, in); } return "备份已恢复";
                    })).show();
            } else if (which == 1) {
                exportFile = file;
                startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("application/zip").putExtra(Intent.EXTRA_TITLE, "ZF-" + file.getName()), EXPORT_SAVE);
            } else {
                if (!editable()) { toast("请先退出游戏"); return; }
                new AlertDialog.Builder(this).setTitle("删除这份备份？").setMessage("当前游戏进度不受影响。")
                    .setNegativeButton("取消", null).setPositiveButton("删除", (a, b) -> task(() -> { storage.deleteBackup(id, file); return "备份已删除"; })).show();
            }
        }).show();
    }
    private void chooseFile(int request) {
        startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*"), request);
    }
    private String fileName(Uri uri) {
        try (android.database.Cursor c = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) return c.getString(0);
        } catch (Exception ignored) {}
        return "导入文件";
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData(); String name = fileName(uri);
        if (request == IMPORT_IPA) task(() -> {
            try (InputStream in = getContentResolver().openInputStream(uri)) { storage.importIpa(in, name); } return "IPA 已导入并选中";
        });
        else if (request == IMPORT_SAVE) {
            final String id = pendingId;
            new AlertDialog.Builder(this).setTitle("导入存档？").setMessage("文件：" + name + "\n当前进度会先自动备份。")
                .setNegativeButton("取消", null).setPositiveButton("导入", (d, w) -> task(() -> {
                    try (BufferedInputStream in = new BufferedInputStream(getContentResolver().openInputStream(uri))) {
                        in.mark(4); int a = in.read(), b = in.read(); in.reset();
                        if (a == 'P' && b == 'K') storage.restore(id, in); else storage.importSave(id, in);
                    } return "存档已导入";
                })).show();
        } else if (request == EXPORT_SAVE && exportFile != null) {
            File source = exportFile;
            task(() -> {
                try (InputStream in = new FileInputStream(source); OutputStream out = getContentResolver().openOutputStream(uri, "wt")) {
                    if (out == null) throw new IOException("无法打开导出位置"); ZfStorage.copy(in, out, 128L * 1024 * 1024);
                } return "备份已导出";
            });
        }
    }
    private void error(Exception e) {
        new AlertDialog.Builder(this).setTitle("操作未完成").setMessage(e.getMessage() == null ? e.toString() : e.getMessage())
            .setPositiveButton("知道了", null).show();
    }
    private void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_LONG).show(); }
}
