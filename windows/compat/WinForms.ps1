# WinForms compatibility UI, loaded by GameManager.ps1 after the shared functions.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:NightModeFile = Join-Path $script:RuntimeRoot 'launcher_night_mode.txt'
$script:NightMode = if (Test-Path -LiteralPath $script:NightModeFile -PathType Leaf) {
    [System.IO.File]::ReadAllText($script:NightModeFile).Trim() -eq '1'
} else { $true }

# Ask before launching when something is already running.
#
# Returns $true when the caller may launch. "Already running" alone is a dead
# end for the player when the process has no window, so that case offers to end
# the leftover instead of just refusing.
function Confirm-NoRunningGame {
    $state = Get-GameProcessState
    if (-not $state.Running) { return $true }

    if ($state.Window -gt 0) {
        Write-ManagerLog ('guard: launch refused, pid={0} has a window' -f $state.Pid)
        Update-Status '游戏已经在运行了。' 'busy'
        return $false
    }

    Write-ManagerLog ('guard: launch refused, pid={0} has no window (source={1})' -f $state.Pid, $state.Source)
    $originalStart = Get-ProcessStartStamp -Process $state.Process
    $answer = [System.Windows.Forms.MessageBox]::Show(
        ("发现一个没有窗口的游戏进程（PID {0}）。`n`n它通常是上次闪退后残留的：任务管理器里看不到游戏窗口，但进程还占着。`n`n结束它并继续吗？" -f $state.Pid),
        '残留的游戏进程', 'YesNo', 'Warning')
    if ($answer -ne 'Yes') { return $false }

    try {
        $current = Get-GameProcessState
        if (-not $current.Running) { return $true }
        if ($current.Window -gt 0 -or $current.Pid -ne $state.Pid -or -not $originalStart -or
            (Get-ProcessStartStamp -Process $current.Process) -ne $originalStart) {
            Update-Status '游戏进程的状态已变化，请再试一次。' 'busy'
            return $false
        }
        Stop-Process -InputObject $current.Process -Force -ErrorAction Stop
        Remove-RunState
        Write-ManagerLog ('guard: ended leftover pid={0}' -f $state.Pid)
        return $true
    } catch {
        Update-Status ("结束残留进程失败：{0}" -f $_.Exception.Message) 'err'
        Write-ManagerLog ('guard: failed to end pid={0}: {1}' -f $state.Pid, $_.Exception.Message)
        return $false
    }
}

# ---------------------------------------------------------------------------
# Single instance
# ---------------------------------------------------------------------------
#
# Two managers used to be able to run side by side. The second one then saw the
# first one's game and said "already running" -- with no manager window anywhere
# to explain why -- and both could write the same options and save files. A
# per-session mutex removes that whole class of confusion.
#
# The name is keyed on the bundle folder, not global: two DIFFERENT installs
# (the dev tree and a Release copy, say) are separate games with separate
# sandboxes and must be able to run at the same time, while two windows onto the
# SAME install are exactly what this has to prevent.
#
# An abandoned mutex means the previous manager died rather than exited; that
# still counts as "we may run".

$instanceKey = ([System.BitConverter]::ToString(
    [System.Security.Cryptography.SHA256]::Create().ComputeHash(
        [System.Text.Encoding]::UTF8.GetBytes($script:HleDir.ToLowerInvariant())))).Replace('-', '').Substring(0, 16)
$script:InstanceMutex = New-Object System.Threading.Mutex($false, ('Local\ZombieFarmManager-' + $instanceKey))
$haveInstance = $false
try {
    $haveInstance = $script:InstanceMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $haveInstance = $true
}
if (-not $haveInstance) {
    [void][System.Windows.Forms.MessageBox]::Show(
        "游戏管理器已经在运行了。`n`n请切换到已经打开的窗口；如果找不到它，说明它正卡在游戏里，先关掉游戏再试。",
        '僵尸农场 · 游戏管理', 'OK', 'Information')
    exit 0
}

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

Add-Type -ReferencedAssemblies @(
    [System.Windows.Forms.TabControl].Assembly.Location,
    [System.Drawing.Color].Assembly.Location
) -TypeDefinition @'
using System;
using System.Drawing;
using System.Windows.Forms;

public sealed class PaletteTabControl : TabControl
{
    private Color stripColor = SystemColors.Control;
    private Color borderColor = SystemColors.ControlDark;
    private Color tabColor = SystemColors.Control;
    private Color selectedTabColor = SystemColors.Highlight;
    private Color tabTextColor = SystemColors.ControlText;
    private Color selectedTabTextColor = SystemColors.HighlightText;

    public Color StripColor
    {
        get { return stripColor; }
        set { stripColor = value; Invalidate(); }
    }

    public Color BorderColor
    {
        get { return borderColor; }
        set { borderColor = value; Invalidate(); }
    }

    public Color TabColor { get { return tabColor; } set { tabColor = value; Invalidate(); } }
    public Color SelectedTabColor { get { return selectedTabColor; } set { selectedTabColor = value; Invalidate(); } }
    public Color TabTextColor { get { return tabTextColor; } set { tabTextColor = value; Invalidate(); } }
    public Color SelectedTabTextColor { get { return selectedTabTextColor; } set { selectedTabTextColor = value; Invalidate(); } }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != 0x000F || !IsHandleCreated || TabCount == 0) return;

        int stripHeight = Math.Max(0, DisplayRectangle.Top);
        if (stripHeight == 0) return;

        using (var graphics = Graphics.FromHwnd(Handle))
        using (var brush = new SolidBrush(stripColor))
        using (var tabBrush = new SolidBrush(tabColor))
        using (var selectedBrush = new SolidBrush(selectedTabColor))
        using (var borderPen = new Pen(borderColor, 2.0f))
        {
            using (var uncovered = new Region(new Rectangle(0, 0, ClientSize.Width, stripHeight)))
            {
                for (int index = 0; index < TabCount; index++)
                    uncovered.Exclude(GetTabRect(index));
                graphics.FillRegion(brush, uncovered);
            }

            for (int index = 0; index < TabCount; index++)
            {
                Rectangle tab = GetTabRect(index);
                bool selected = index == SelectedIndex;
                graphics.FillRectangle(selected ? selectedBrush : tabBrush, tab);
                graphics.DrawRectangle(borderPen, tab.X, tab.Y, tab.Width - 1, tab.Height - 1);
                TextRenderer.DrawText(graphics, TabPages[index].Text.Trim(), Font, tab,
                    selected ? selectedTabTextColor : tabTextColor,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                    TextFormatFlags.NoPrefix | TextFormatFlags.EndEllipsis);
            }

            Rectangle page = DisplayRectangle;
            page.Inflate(1, 1);
            graphics.DrawRectangle(borderPen, page);
            Rectangle frame = ClientRectangle;
            frame.Inflate(-1, -1);
            graphics.DrawRectangle(borderPen, frame);
        }
    }
}

public sealed class PaletteComboBox : ComboBox
{
    private Color arrowColor;
    private Color arrowBorderColor;
    private Color arrowGlyphColor;

    public PaletteComboBox()
    {
        arrowColor = SystemColors.Control;
        arrowBorderColor = SystemColors.ControlDark;
        arrowGlyphColor = SystemColors.ControlText;
    }

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams parameters = base.CreateParams;
            parameters.ExStyle &= ~0x00000200; // WS_EX_CLIENTEDGE
            parameters.Style &= ~0x00800000;   // WS_BORDER
            return parameters;
        }
    }

    public Color ArrowColor { get { return arrowColor; } set { arrowColor = value; Invalidate(); } }
    public Color ArrowBorderColor { get { return arrowBorderColor; } set { arrowBorderColor = value; Invalidate(); } }
    public Color ArrowGlyphColor { get { return arrowGlyphColor; } set { arrowGlyphColor = value; Invalidate(); } }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != 0x000F || !IsHandleCreated || ClientSize.Width == 0) return;

        int arrowWidth = Math.Min(SystemInformation.VerticalScrollBarWidth, ClientSize.Width);
        Rectangle arrow = new Rectangle(ClientSize.Width - arrowWidth, 0, arrowWidth, ClientSize.Height);
        using (var graphics = Graphics.FromHwnd(Handle))
        using (var background = new SolidBrush(ArrowColor))
        using (var border = new Pen(ArrowBorderColor))
        using (var glyph = new SolidBrush(ArrowGlyphColor))
        {
            // The themed combo arrow leaves a one-pixel white seam before its
            // client area; overlap that pixel so the palette owns the separator.
            graphics.FillRectangle(background, arrow.Left - 1, 0, arrow.Width + 1, arrow.Height);
            graphics.DrawLine(border, arrow.Left, 2, arrow.Left, arrow.Bottom - 3);
            int cx = arrow.Left + arrow.Width / 2;
            int cy = arrow.Top + arrow.Height / 2;
            graphics.FillPolygon(glyph, new[] {
                new Point(cx - 4, cy - 2), new Point(cx + 4, cy - 2), new Point(cx, cy + 3)
            });
            graphics.DrawRectangle(border, 0, 0, ClientSize.Width - 1, ClientSize.Height - 1);
        }
    }
}

public sealed class PaletteGroupBox : GroupBox
{
    private Color borderColor;

    public PaletteGroupBox() { borderColor = SystemColors.ControlDark; }

    public Color BorderColor { get { return borderColor; } set { borderColor = value; Invalidate(); } }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != 0x000F || !IsHandleCreated || Width < 8 || Height < 8) return;

        int y = Math.Max(5, Font.Height / 2);
        int gapStart = 8;
        int gapEnd = gapStart + (Text.Length == 0 ? 0 : TextRenderer.MeasureText(Text, Font).Width) + 8;
        using (var graphics = Graphics.FromHwnd(Handle))
        using (var border = new Pen(BorderColor, 2.0f))
        {
            graphics.DrawLine(border, 0, y, gapStart, y);
            graphics.DrawLine(border, gapEnd, y, Width - 1, y);
            graphics.DrawLine(border, 0, y, 0, Height - 1);
            graphics.DrawLine(border, Width - 1, y, Width - 1, Height - 1);
            graphics.DrawLine(border, 0, Height - 1, Width - 1, Height - 1);
        }
    }
}

public static class WindowChrome
{
    [System.Runtime.InteropServices.DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr insertAfter, int x, int y,
        int width, int height, uint flags);

    public static int PackColor(Color color)
    {
        return color.R | (color.G << 8) | (color.B << 16);
    }

    public static void Apply(IntPtr hwnd, bool night, int caption, int text, int border)
    {
        int dark = night ? 1 : 0;
        int result = DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int));
        if (result != 0) DwmSetWindowAttribute(hwnd, 19, ref dark, sizeof(int));

        DwmSetWindowAttribute(hwnd, 35, ref caption, sizeof(int));
        DwmSetWindowAttribute(hwnd, 36, ref text, sizeof(int));
        DwmSetWindowAttribute(hwnd, 34, ref border, sizeof(int));
        SetWindowPos(hwnd, IntPtr.Zero, 0, 0, 0, 0, 0x0027);
    }
}
'@

$font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9.5)
$fontBold = New-Object System.Drawing.Font('Microsoft YaHei UI', 10.5, [System.Drawing.FontStyle]::Bold)
$fontTitle = New-Object System.Drawing.Font('Microsoft YaHei UI', 15, [System.Drawing.FontStyle]::Bold)
$fontSmall = New-Object System.Drawing.Font('Microsoft YaHei UI', 8.5)
# Hashes read much better in a fixed-width face: 16 hex digits in YaHei are
# painful to compare against the numbers on the release page.
$fontMono = New-Object System.Drawing.Font('Consolas', 8.5)
if ($script:NightMode) {
    $ink = [System.Drawing.Color]::FromArgb(232, 237, 234)
    $grey = [System.Drawing.Color]::FromArgb(165, 179, 173)
    $red = [System.Drawing.Color]::FromArgb(224, 126, 116)
    $forest = [System.Drawing.Color]::FromArgb(76, 139, 111)
    $sage = [System.Drawing.Color]::FromArgb(126, 177, 146)
    $amber = [System.Drawing.Color]::FromArgb(214, 168, 99)
    $paper = [System.Drawing.Color]::FromArgb(29, 35, 38)
    $surface = [System.Drawing.Color]::FromArgb(38, 46, 48)
    $softGreen = [System.Drawing.Color]::FromArgb(48, 65, 56)
    $line = [System.Drawing.Color]::FromArgb(49, 59, 56)
} else {
    $ink = [System.Drawing.Color]::FromArgb(38, 52, 58)
    $grey = [System.Drawing.Color]::FromArgb(105, 122, 120)
    $red = [System.Drawing.Color]::FromArgb(184, 78, 74)
    $forest = [System.Drawing.Color]::FromArgb(45, 101, 87)
    $sage = [System.Drawing.Color]::FromArgb(111, 148, 127)
    $amber = [System.Drawing.Color]::FromArgb(214, 160, 82)
    $paper = [System.Drawing.Color]::FromArgb(243, 246, 244)
    $surface = [System.Drawing.Color]::White
    $softGreen = [System.Drawing.Color]::FromArgb(228, 236, 231)
    $line = [System.Drawing.Color]::FromArgb(220, 228, 223)
}

$script:PaletteComboDraw = {
    param($sender, $eventArgs)
    $label = if ($eventArgs.Index -ge 0) { [string]$sender.Items[$eventArgs.Index] } else { [string]$sender.Text }
    $selected = ($eventArgs.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0
    $background = if ($selected) { $script:Forest } else { $script:Surface }
    $foreground = if ($selected) { [System.Drawing.Color]::White } else { $script:Ink }
    $fill = New-Object System.Drawing.SolidBrush($background)
    $textBrush = New-Object System.Drawing.SolidBrush($foreground)
    try {
        $eventArgs.Graphics.FillRectangle($fill, $eventArgs.Bounds)
        $size = $eventArgs.Graphics.MeasureString($label, $sender.Font)
        $x = $eventArgs.Bounds.Left + 4
        $y = $eventArgs.Bounds.Top + (($eventArgs.Bounds.Height - $size.Height) / 2)
        $eventArgs.Graphics.DrawString($label, $sender.Font, $textBrush, [single]$x, [single]$y)
    } finally { $fill.Dispose(); $textBrush.Dispose() }
}

$form = New-Object System.Windows.Forms.Form
# "免费开源" rides along in the title bar so it is visible in the taskbar and
# in any screenshot of the window. Automation matches this title with
# -match 'Zombie Farm', so the prefix must keep that phrase intact.
$form.Text = 'Zombie Farm 游戏管理 · 免费开源'
# Height is sized to the content (see the tab height below) rather than padded out,
# so there is no dead space at the bottom of either tab.
$form.ClientSize = New-Object System.Drawing.Size(960, 574)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = $font
$form.BackColor = $paper
$form.ForeColor = $ink

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Zombie Farm 游戏管理'
$title.Font = $fontTitle
$title.ForeColor = $ink
$title.Location = New-Object System.Drawing.Point(22, 12)
$title.AutoSize = $true
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text = '设置写入 touchHLE_options.txt，只影响 Zombie Farm；改动立即保存'
$subtitle.Font = $fontSmall
$subtitle.ForeColor = $grey
$subtitle.Location = New-Object System.Drawing.Point(24, 44)
$subtitle.AutoSize = $true
$form.Controls.Add($subtitle)

$btnTheme = New-Object System.Windows.Forms.Button
$btnTheme.Location = New-Object System.Drawing.Point(900, 11)
$btnTheme.Size = New-Object System.Drawing.Size(38, 38)
$btnTheme.FlatStyle = 'Flat'
$btnTheme.FlatAppearance.BorderSize = 1
$btnTheme.UseVisualStyleBackColor = $false
$btnTheme.Text = ''
$btnTheme.Font = New-Object System.Drawing.Font('Segoe MDL2 Assets', 13)
$btnTheme.AccessibleName = '日夜模式切换'
$btnTheme.Add_Paint({
    param($sender, $eventArgs)
    $glyph = [string]$sender.Tag
    if (-not $glyph) { return }

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $brush = New-Object System.Drawing.SolidBrush($sender.ForeColor)
    $format = [System.Drawing.StringFormat]::GenericTypographic.Clone()
    $transform = New-Object System.Drawing.Drawing2D.Matrix
    try {
        $emSize = [single]($sender.Font.SizeInPoints * $eventArgs.Graphics.DpiY / 72.0)
        $path.AddString(
            $glyph, $sender.Font.FontFamily, [int]$sender.Font.Style, $emSize,
            [System.Drawing.PointF]::new(0, 0), $format)
        $ink = $path.GetBounds()
        $client = $sender.ClientRectangle
        $x = $client.Left + (($client.Width - $ink.Width) / 2) - $ink.Left
        $y = $client.Top + (($client.Height - $ink.Height) / 2) - $ink.Top
        $opticalX = 0.0
        $opticalY = 0.0
        if ($glyph -eq [string][char]0xE708) {
            # The crescent's visible ink centroid sits right and low of its path bounds.
            $dpiScale = $eventArgs.Graphics.DpiY / 96.0
            $opticalX = -1.65 * $dpiScale
            $opticalY = -1.20 * $dpiScale
        }
        $transform.Translate([single]($x + $opticalX), [single]($y + $opticalY))
        $path.Transform($transform)
        $eventArgs.Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $eventArgs.Graphics.FillPath($brush, $path)
    } finally {
        $path.Dispose(); $brush.Dispose(); $format.Dispose(); $transform.Dispose()
    }
})
$form.Controls.Add($btnTheme)
$themeTip = New-Object System.Windows.Forms.ToolTip

# A restrained gold rule separates the app heading from the page navigation.
$headerRule = New-Object System.Windows.Forms.Panel
$headerRule.Location = New-Object System.Drawing.Point(22, 63)
$headerRule.Size = New-Object System.Drawing.Size(916, 2)
$headerRule.BackColor = $amber
$form.Controls.Add($headerRule)

$tabs = New-Object PaletteTabControl
$tabs.Location = New-Object System.Drawing.Point(20, 72)
# Height is set at the bottom of this file, once every tab's contents exist, so it
# always matches the taller tab. Hardcoding it meant the game tab (which grew when
# the IPA picker was added) ended up flush against the tab's bottom edge.
$tabs.Size = New-Object System.Drawing.Size(920, 100)
$tabs.Font = $font
$tabs.DrawMode = [System.Windows.Forms.TabDrawMode]::OwnerDrawFixed
$tabs.Appearance = [System.Windows.Forms.TabAppearance]::FlatButtons
$form.Controls.Add($tabs)

$tabGame = New-Object System.Windows.Forms.TabPage
$tabGame.Text = '  游戏  '
$tabGame.UseVisualStyleBackColor = $false
$tabGame.BackColor = $paper
$tabs.Controls.Add($tabGame)

$tabSettings = New-Object System.Windows.Forms.TabPage
$tabSettings.Text = '  设置  '
$tabSettings.UseVisualStyleBackColor = $false
$tabSettings.BackColor = $paper
$tabs.Controls.Add($tabSettings)

$tabSave = New-Object System.Windows.Forms.TabPage
$tabSave.Text = '  存档  '
$tabSave.UseVisualStyleBackColor = $false
$tabSave.BackColor = $paper
$tabs.Controls.Add($tabSave)

# --- game tab: IPA selection ------------------------------------------------
#
# Which IPA to launch. The folder holds three different bundle identifiers, and
# both touchHLE_options.txt and the sandbox save folder are keyed on that id, so
# switching IPA also switches which settings line applies and which saves are
# visible -- the label under the dropdown spells that out.

$grpIpa = New-Object PaletteGroupBox
$grpIpa.Text = '游戏版本 (IPA)'
$grpIpa.Location = New-Object System.Drawing.Point(14, 8)
$grpIpa.Size = New-Object System.Drawing.Size(892, 74)
$grpIpa.Font = $font
$tabGame.Controls.Add($grpIpa)

$cmbIpa = New-Object PaletteComboBox
$cmbIpa.Location = New-Object System.Drawing.Point(14, 26)
$cmbIpa.Size = New-Object System.Drawing.Size(778, 24)
$cmbIpa.DropDownStyle = 'DropDownList'
$cmbIpa.DrawMode = 'OwnerDrawFixed'
$cmbIpa.ItemHeight = 20
$cmbIpa.FlatStyle = 'Flat'
$cmbIpa.Add_DrawItem($script:PaletteComboDraw)
$cmbIpa.Font = $font
$grpIpa.Controls.Add($cmbIpa)

$btnIpaBrowse = New-Object System.Windows.Forms.Button
$btnIpaBrowse.Text = '浏览…'
$btnIpaBrowse.Location = New-Object System.Drawing.Point(800, 25)
$btnIpaBrowse.Size = New-Object System.Drawing.Size(76, 26)
$btnIpaBrowse.FlatStyle = 'Flat'
$grpIpa.Controls.Add($btnIpaBrowse)

$lblIpaInfo = New-Object System.Windows.Forms.Label
$lblIpaInfo.Text = ''
$lblIpaInfo.Location = New-Object System.Drawing.Point(14, 52)
$lblIpaInfo.Size = New-Object System.Drawing.Size(860, 18)
$lblIpaInfo.Font = $fontSmall
$lblIpaInfo.ForeColor = $grey
$grpIpa.Controls.Add($lblIpaInfo)

# --- game tab: launch buttons ----------------------------------------------

$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = '启动游戏'
$btnStart.Location = New-Object System.Drawing.Point(16, 92)
$btnStart.Size = New-Object System.Drawing.Size(430, 52)
$btnStart.Font = $fontBold
$btnStart.BackColor = $forest
$btnStart.ForeColor = [System.Drawing.Color]::White
$btnStart.FlatStyle = 'Flat'
$btnStart.FlatAppearance.BorderSize = 0
$tabGame.Controls.Add($btnStart)

$btnStartSkip = New-Object System.Windows.Forms.Button
$btnStartSkip.Text = '启动并跳过时间…'
$btnStartSkip.Location = New-Object System.Drawing.Point(456, 92)
$btnStartSkip.Size = New-Object System.Drawing.Size(430, 52)
$btnStartSkip.FlatStyle = 'Flat'
$btnStartSkip.BackColor = $softGreen
$btnStartSkip.ForeColor = $forest
$tabGame.Controls.Add($btnStartSkip)

$lblSimulatedTime = New-Object System.Windows.Forms.Label
$lblSimulatedTime.Text = '模拟时间：读取中…'
$lblSimulatedTime.Location = New-Object System.Drawing.Point(16, 153)
$lblSimulatedTime.Size = New-Object System.Drawing.Size(670, 21)
$lblSimulatedTime.Font = $fontSmall
$tabGame.Controls.Add($lblSimulatedTime)

$btnResetTime = New-Object System.Windows.Forms.Button
$btnResetTime.Text = '重置为当前时间'
$btnResetTime.Location = New-Object System.Drawing.Point(704, 150)
$btnResetTime.Size = New-Object System.Drawing.Size(182, 27)
$btnResetTime.FlatStyle = 'Flat'
$btnResetTime.BackColor = $softGreen
$btnResetTime.ForeColor = $forest
$btnResetTime.Visible = $false
$tabGame.Controls.Add($btnResetTime)

# --- settings tab ---------------------------------------------------------

# Rows are laid out at a fixed pitch and the group box height is derived from the
# number of ROWS, so adding or removing a setting cannot leave a blank gap or clip
# the last row. Longer explanations live in 使用说明.html.
#
# A setting may share a row with another by naming the same `Row`; window_family
# and window_scale do, because the user asked for them side by side ("左边可以选
# ipad ... 右侧可以自定义 --scale-hack"). Sharing a row is why the height counts
# distinct Row names rather than SettingDefs entries.
$script:RowPitch = 40

$script:RowNames = @()
foreach ($key in $script:SettingDefs.Keys) {
    $def = $script:SettingDefs[$key]
    $row = if ($def.ContainsKey('Row')) { $def.Row } else { $key }
    if ($script:RowNames -notcontains $row) { $script:RowNames += $row }
}

$grpSettings = New-Object PaletteGroupBox
$grpSettings.Text = '设置'
$grpSettings.Location = New-Object System.Drawing.Point(147, 10)
$grpSettings.Height = ($script:RowNames.Count * $script:RowPitch) + 26
$grpSettings.Width = 626
$tabSettings.Controls.Add($grpSettings)

$script:Controls = @{}
# Per-setting numeric/text editor for the 自定义 entry, plus its label and unit,
# so Update-CustomEnabled can enable/disable the whole triple.
$script:CustomEditors = @{}
# Row name -> its Y offset. NOTE: the local read below must NOT be named `$rowY`,
# because PowerShell variable names are case-INSENSITIVE, so a plain `$rowY` at
# script scope IS `$script:RowY` - assigning the integer would destroy the
# hashtable on the very first iteration.
$script:RowOffsets = @{}
$y = 26
foreach ($key in $script:SettingDefs.Keys) {
    $def = $script:SettingDefs[$key]
    $row = if ($def.ContainsKey('Row')) { $def.Row } else { $key }
    if (-not $script:RowOffsets.ContainsKey($row)) {
        $script:RowOffsets[$row] = $y
        $y += $script:RowPitch
    }
    $rowY = $script:RowOffsets[$row]

    # An empty Label means this control shares the row's label with a neighbour.
    if ($def.Label) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $def.Label
        $width = if ($def.ContainsKey('LabelWidth')) { $def.LabelWidth } else { 150 }
        $lbl.Location = New-Object System.Drawing.Point(14, ($rowY + 5))
        $lbl.Size = New-Object System.Drawing.Size($width, 22)
        $grpSettings.Controls.Add($lbl)
    }

    $comboX = if ($def.ContainsKey('ComboX')) { $def.ComboX } else { 170 }
    $comboW = if ($def.ContainsKey('ComboW')) { $def.ComboW } else { 200 }

    $combo = New-Object PaletteComboBox
    $combo.Location = New-Object System.Drawing.Point($comboX, $rowY)
    $combo.Size = New-Object System.Drawing.Size($comboW, 24)
    $combo.DropDownStyle = 'DropDownList'
    $combo.DrawMode = 'OwnerDrawFixed'
    $combo.ItemHeight = 20
    $combo.FlatStyle = 'Flat'
    $combo.Add_DrawItem($script:PaletteComboDraw)
    $combo.Tag = $key
    # Plain values only: long "value — explanation" strings overflowed the control.
    # The explanation lives in 使用说明.html (shipped beside the manager).
    foreach ($choice in $def.Choices) {
        [void]$combo.Items.Add($choice.Text)
    }
    $grpSettings.Controls.Add($combo)
    $script:Controls[$key] = $combo

    # A setting with AllowCustom gets an extra editor for its 自定义 entry, only
    # enabled while 自定义 is selected.
    if ($def.AllowCustom) {
        $kind = if ($def.ContainsKey('CustomKind')) { $def.CustomKind } else { 'int' }
        $editorX = if ($def.ContainsKey('CustomX')) { $def.CustomX } else { 496 }
        $editorW = if ($def.ContainsKey('CustomWidth')) { $def.CustomWidth } else { 80 }

        # An empty CustomLabel means the editor needs no label of its own (the
        # dropdown right before it already says 自定义).
        if ($def.CustomLabel) {
            $lblCustom = New-Object System.Windows.Forms.Label
            $lblCustom.Text = $def.CustomLabel
            $lblCustom.Location = New-Object System.Drawing.Point(($editorX - 76), ($rowY + 5))
            $lblCustom.Size = New-Object System.Drawing.Size(74, 22)
            $lblCustom.TextAlign = 'MiddleRight'
            $grpSettings.Controls.Add($lblCustom)
        } else {
            $lblCustom = $null
        }

        if ($kind -eq 'scale') {
            # --scale-hack is parsed by touchHLE itself, which accepts a fraction
            # ("7/4") as well as a decimal ("1.75"). A NumericUpDown cannot express
            # a fraction, and silently rewriting a hand-edited 13/8 into a rounded
            # decimal would change the window size behind the user's back - so the
            # scale entry is a text box validated against exactly the grammar
            # touchHLE accepts (Test-CustomSpelling).
            $editor = New-Object System.Windows.Forms.TextBox
            $editor.TextAlign = 'Center'
            # Start from the preset the user is leaving, so selecting 自定义 does
            # not blank the value and leave the setting in limbo. Load-SettingsIntoUi
            # overwrites this with the stored value when there is one.
            $editor.Text = if ($def.ContainsKey('CustomInitial')) { [string]$def.CustomInitial } else { [string]$def.Default }
        } else {
            $editor = New-Object System.Windows.Forms.TextBox
            # DecimalPlaces must be set BEFORE Minimum/Maximum: the bounds are
            # coerced to the current precision when assigned, so setting 1.01 as a
            # minimum while DecimalPlaces is still 0 would silently store 1.
            $decimals = if ($def.ContainsKey('CustomDecimals')) { [int]$def.CustomDecimals } else { 0 }
            $step = if ($def.ContainsKey('CustomStep')) { [decimal]$def.CustomStep } else { [decimal]1 }
            # Start at a sensible value rather than at Minimum: selecting 自定义
            # would otherwise immediately mean 1 fps (or a 1.01 zoom step), and
            # the user would have to correct it before the setting was usable.
            $initial = if ($def.ContainsKey('CustomInitial')) { [decimal]$def.CustomInitial } else { [decimal]$def.CustomMin }
            $editor.TextAlign = 'Center'
            $editor.MaxLength = 12
            $editor.Text = [string][Math]::Min([Math]::Max($initial, [decimal]$def.CustomMin), [decimal]$def.CustomMax)
        }
        $editor.Location = New-Object System.Drawing.Point($editorX, $rowY)
        $editor.Size = New-Object System.Drawing.Size($editorW, 24)
        $editor.Tag = $key
        $grpSettings.Controls.Add($editor)

        $lblUnit = $null
        if ($def.ContainsKey('CustomSuffix') -and $def.CustomSuffix) {
            $lblUnit = New-Object System.Windows.Forms.Label
            $lblUnit.Text = $def.CustomSuffix
            $lblUnit.Location = New-Object System.Drawing.Point(($editorX + $editorW + 4), ($rowY + 5))
            $lblUnit.Size = New-Object System.Drawing.Size(24, 22)
            $grpSettings.Controls.Add($lblUnit)
        }

        $script:CustomEditors[$key] = @{
            Kind   = $kind
            Editor = $editor
            Label  = $lblCustom
            Unit   = $lblUnit
        }
    }

    # The window row ends with a live readout of the size the family+scale pair
    # actually produces, so the two dropdowns still read as one decision. With the
    # "?" buttons gone there is room for a wider readout, so a 4-digit size like
    # 1792 × 1344 is never clipped.
    if ($key -eq 'window_scale') {
        $script:LblWindowSize = New-Object System.Windows.Forms.Label
        $script:LblWindowSize.Text = ''
        $script:LblWindowSize.Location = New-Object System.Drawing.Point(452, ($rowY + 5))
        $script:LblWindowSize.Size = New-Object System.Drawing.Size(164, 22)
        $script:LblWindowSize.Font = $fontSmall
        $script:LblWindowSize.ForeColor = $sage
        $grpSettings.Controls.Add($script:LblWindowSize)
    }
}

# --- game tab: currency ----------------------------------------------------

$grpCurrency = New-Object PaletteGroupBox
$grpCurrency.Text = '金币与脑子'
$grpCurrency.Location = New-Object System.Drawing.Point(14, 183)
$grpCurrency.Size = New-Object System.Drawing.Size(892, 112)
$tabGame.Controls.Add($grpCurrency)

$lblGold = New-Object System.Windows.Forms.Label
$lblGold.Text = '金币'
$lblGold.Location = New-Object System.Drawing.Point(20, 34)
$lblGold.Size = New-Object System.Drawing.Size(50, 22)
$grpCurrency.Controls.Add($lblGold)

$numGold = New-Object System.Windows.Forms.TextBox
$numGold.Location = New-Object System.Drawing.Point(75, 31)
$numGold.Size = New-Object System.Drawing.Size(240, 24)
$numGold.MaxLength = 10
$numGold.TextAlign = 'Center'
$numGold.Text = '0'
$grpCurrency.Controls.Add($numGold)

$lblBrains = New-Object System.Windows.Forms.Label
$lblBrains.Text = '脑子'
$lblBrains.Location = New-Object System.Drawing.Point(350, 34)
$lblBrains.Size = New-Object System.Drawing.Size(50, 22)
$grpCurrency.Controls.Add($lblBrains)

$numBrains = New-Object System.Windows.Forms.TextBox
$numBrains.Location = New-Object System.Drawing.Point(405, 31)
$numBrains.Size = New-Object System.Drawing.Size(240, 24)
$numBrains.MaxLength = 10
$numBrains.TextAlign = 'Center'
$numBrains.Text = '0'
$grpCurrency.Controls.Add($numBrains)

$btnApplyCurrency = New-Object System.Windows.Forms.Button
$btnApplyCurrency.Text = '写入存档'
$btnApplyCurrency.Location = New-Object System.Drawing.Point(665, 28)
$btnApplyCurrency.Size = New-Object System.Drawing.Size(210, 30)
$btnApplyCurrency.FlatStyle = 'Flat'
$grpCurrency.Controls.Add($btnApplyCurrency)

$lblCurrencyState = New-Object System.Windows.Forms.Label
$lblCurrencyState.Text = ''
$lblCurrencyState.Location = New-Object System.Drawing.Point(20, 69)
$lblCurrencyState.Size = New-Object System.Drawing.Size(850, 24)
$lblCurrencyState.Font = $fontSmall
$lblCurrencyState.ForeColor = $grey
$grpCurrency.Controls.Add($lblCurrencyState)

# --- save tab --------------------------------------------------------------

$lblSaveInfo = New-Object System.Windows.Forms.Label
$lblSaveInfo.Text = ''
$lblSaveInfo.Location = New-Object System.Drawing.Point(14, 14)
$lblSaveInfo.Size = New-Object System.Drawing.Size(892, 22)
$lblSaveInfo.Font = $fontSmall
$lblSaveInfo.ForeColor = $grey
$tabSave.Controls.Add($lblSaveInfo)

$btnBackup = New-Object System.Windows.Forms.Button
$btnBackup.Text = '新增备份'
$btnBackup.Location = New-Object System.Drawing.Point(14, 42)
$btnBackup.Size = New-Object System.Drawing.Size(180, 36)
$btnBackup.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnBackup)

$btnRestore = New-Object System.Windows.Forms.Button
$btnRestore.Text = '还原所选备份'
$btnRestore.Location = New-Object System.Drawing.Point(238, 42)
$btnRestore.Size = New-Object System.Drawing.Size(210, 36)
$btnRestore.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnRestore)

$btnDelete = New-Object System.Windows.Forms.Button
$btnDelete.Text = '删除所选'
$btnDelete.Location = New-Object System.Drawing.Point(462, 42)
$btnDelete.Size = New-Object System.Drawing.Size(210, 36)
$btnDelete.FlatStyle = 'Flat'
$btnDelete.ForeColor = $forest
$tabSave.Controls.Add($btnDelete)

$btnRefresh = New-Object System.Windows.Forms.Button
$btnRefresh.Text = '刷新'
$btnRefresh.Location = New-Object System.Drawing.Point(686, 42)
$btnRefresh.Size = New-Object System.Drawing.Size(210, 36)
$btnRefresh.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnRefresh)

$listSaves = New-Object System.Windows.Forms.ListView
$listSaves.Location = New-Object System.Drawing.Point(14, 90)
$listSaves.Size = New-Object System.Drawing.Size(892, 272)
$listSaves.View = 'Details'
$listSaves.FullRowSelect = $true
# Multi-select so several backups can be deleted at once. Restore stays
# single-selection: restoring two saves at the same time is meaningless.
$listSaves.MultiSelect = $true
$listSaves.HideSelection = $false
$listSaves.GridLines = $false
$listSaves.OwnerDraw = $true
$listSaves.BorderStyle = 'None'
$listSaves.Font = $fontSmall
[void]$listSaves.Columns.Add('类型', 100)
[void]$listSaves.Columns.Add('备份文件', 560)
[void]$listSaves.Columns.Add('大小', 80, 'Right')
[void]$listSaves.Columns.Add('时间', 100)
$resizeSaveColumns = {
    param($sender, $eventArgs)
    $fixedWidth = $sender.Columns[0].Width + $sender.Columns[1].Width + $sender.Columns[2].Width
    $sender.Columns[3].Width = [Math]::Max(100, ($sender.ClientSize.Width - $fixedWidth))
}
$listSaves.Add_Resize($resizeSaveColumns)
$resizeSaveColumns.Invoke($listSaves, [EventArgs]::Empty)
$listSaves.Add_DrawColumnHeader({
    param($sender, $eventArgs)
    $background = New-Object System.Drawing.SolidBrush($script:Surface)
    $linePen = New-Object System.Drawing.Pen($script:Line)
    try {
        $eventArgs.Graphics.FillRectangle($background, $eventArgs.Bounds)
        $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::EndEllipsis -bor
            [System.Windows.Forms.TextFormatFlags]::NoPrefix
        switch ($eventArgs.Header.TextAlign) {
            'Right'  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Right }
            'Center' { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::HorizontalCenter }
            default  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Left }
        }
        $bounds = $eventArgs.Bounds
        $bounds.Inflate(-6, 0)
        [System.Windows.Forms.TextRenderer]::DrawText(
            $eventArgs.Graphics, $eventArgs.Header.Text, $eventArgs.Font,
            $bounds, $script:Ink, $flags)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Left,
            $eventArgs.Bounds.Bottom - 1, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Top, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
    } finally {
        $background.Dispose(); $linePen.Dispose()
    }
})
$listSaves.Add_DrawItem({
    param($sender, $eventArgs)
    if ($sender.View -ne [System.Windows.Forms.View]::Details) { $eventArgs.DrawDefault() }
})
$listSaves.Add_DrawSubItem({
    param($sender, $eventArgs)
    # Native custom-draw ItemState can report Selected for every subitem.
    # Read the actual row state, including when focus moves to an action button.
    $selected = $eventArgs.Item.Selected
    $background = if ($selected) { $script:SaveSelection } else { $script:Surface }
    $foreground = if ($selected) { $script:Ink } else { $eventArgs.Item.ForeColor }
    if ($foreground.IsEmpty -or $foreground -eq [System.Drawing.Color]::Empty) {
        $foreground = $script:Ink
    }
    $fill = New-Object System.Drawing.SolidBrush($background)
    $linePen = New-Object System.Drawing.Pen($script:Line)
    try {
        $eventArgs.Graphics.FillRectangle($fill, $eventArgs.Bounds)
        if ($selected -and $eventArgs.ColumnIndex -eq 0) {
            $accent = New-Object System.Drawing.SolidBrush($script:SaveSelectionAccent)
            try {
                $eventArgs.Graphics.FillRectangle($accent, $eventArgs.Bounds.Left,
                    $eventArgs.Bounds.Top, 3, $eventArgs.Bounds.Height - 1)
            } finally { $accent.Dispose() }
        }
        $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::EndEllipsis -bor
            [System.Windows.Forms.TextFormatFlags]::NoPrefix
        switch ($eventArgs.Header.TextAlign) {
            'Right'  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Right }
            'Center' { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::HorizontalCenter }
            default  { $flags = $flags -bor [System.Windows.Forms.TextFormatFlags]::Left }
        }
        $bounds = $eventArgs.Bounds
        $bounds.Inflate(-6, 0)
        [System.Windows.Forms.TextRenderer]::DrawText(
            $eventArgs.Graphics, $eventArgs.SubItem.Text, $eventArgs.SubItem.Font,
            $bounds, $foreground, $flags)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Left,
            $eventArgs.Bounds.Bottom - 1, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
        $eventArgs.Graphics.DrawLine($linePen, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Top, $eventArgs.Bounds.Right - 1,
            $eventArgs.Bounds.Bottom - 1)
    } finally { $fill.Dispose(); $linePen.Dispose() }
})
$tabSave.Controls.Add($listSaves)

# Select-all / invert helpers: clicking through dozens of rows one at a time to
# delete them is exactly the chore this tab should remove.
$btnSelectAll = New-Object System.Windows.Forms.Button
$btnSelectAll.Text = '全选备份'
$btnSelectAll.Location = New-Object System.Drawing.Point(14, 368)
$btnSelectAll.Size = New-Object System.Drawing.Size(120, 28)
$btnSelectAll.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnSelectAll)

$btnSelectNone = New-Object System.Windows.Forms.Button
$btnSelectNone.Text = '取消选择'
$btnSelectNone.Location = New-Object System.Drawing.Point(142, 368)
$btnSelectNone.Size = New-Object System.Drawing.Size(120, 28)
$btnSelectNone.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnSelectNone)

$btnSelectInvert = New-Object System.Windows.Forms.Button
$btnSelectInvert.Text = '反选'
$btnSelectInvert.Location = New-Object System.Drawing.Point(270, 368)
$btnSelectInvert.Size = New-Object System.Drawing.Size(120, 28)
$btnSelectInvert.FlatStyle = 'Flat'
$tabSave.Controls.Add($btnSelectInvert)

$lblSaveHint = New-Object System.Windows.Forms.Label
$lblSaveHint.Text = ''
$lblSaveHint.Location = New-Object System.Drawing.Point(400, 374)
$lblSaveHint.Size = New-Object System.Drawing.Size(500, 20)
$lblSaveHint.Font = $fontSmall
$lblSaveHint.ForeColor = $grey
$tabSave.Controls.Add($lblSaveHint)

# --- verify tab -------------------------------------------------------------
#
# Publishing a SHA-256 next to the release only helps if the player can see the
# local one. This page puts them side by side and says outright which file does
# not match -- a hash nobody can find is not a check.
#
# GameManager.ps1 is listed but not pinned: its expected hash cannot live inside
# the file being hashed. It is shown so it can be compared with the release
# notes, which is the one number an editor of this file cannot forge.

$tabVerify = New-Object System.Windows.Forms.TabPage
$tabVerify.Text = '  文件校验  '
$tabVerify.UseVisualStyleBackColor = $false
$tabVerify.BackColor = $paper
$tabs.Controls.Add($tabVerify)

$grpVerify = New-Object PaletteGroupBox
$grpVerify.Text = '官方文件指纹'
$grpVerify.Location = New-Object System.Drawing.Point(14, 8)
$grpVerify.Size = New-Object System.Drawing.Size(892, 172)
$grpVerify.Font = $font
$tabVerify.Controls.Add($grpVerify)

$script:VerifyHeaderLabels = New-Object System.Collections.ArrayList
foreach ($h in @(
    @{ Text = '文件';                     X = 14;  W = 214 },
    @{ Text = '官方 SHA-256（前 16 位）'; X = 232; W = 190 },
    @{ Text = '本机实际（前 16 位）';     X = 430; W = 190 },
    @{ Text = '结果';                     X = 628; W = 254 }
)) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = $h.Text
    $lbl.Location = New-Object System.Drawing.Point($h.X, 24)
    $lbl.Size = New-Object System.Drawing.Size($h.W, 18)
    $lbl.Font = $fontSmall
    $lbl.ForeColor = $grey
    $grpVerify.Controls.Add($lbl)
    [void]$script:VerifyHeaderLabels.Add($lbl)
}

# Filled in by Update-IntegrityDisplay, which is defined further down with the
# other hash helpers. The controls exist now so the page can be laid out before
# anything is hashed.
$script:VerifyRowControls = New-Object System.Collections.ArrayList
for ($row = 0; $row -lt 3; $row++) {
    $top = 48 + ($row * 32)
    $entry = @{}
    foreach ($spec in @(
        @{ Key = 'Name';    X = 14;  W = 214; Font = $fontSmall },
        @{ Key = 'Expect';  X = 232; W = 190; Font = $fontMono },
        @{ Key = 'Actual';  X = 430; W = 190; Font = $fontMono },
        @{ Key = 'Verdict'; X = 628; W = 254; Font = $fontSmall }
    )) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = ''
        $lbl.Location = New-Object System.Drawing.Point($spec.X, $top)
        $lbl.Size = New-Object System.Drawing.Size($spec.W, 20)
        $lbl.Font = $spec.Font
        $grpVerify.Controls.Add($lbl)
        $entry[$spec.Key] = $lbl
    }
    [void]$script:VerifyRowControls.Add($entry)
}

# Which IPA is selected right now. Running a different one is allowed, so this
# is informational: it explains what the three rows above are actually about.
$script:LblVerifySelection = New-Object System.Windows.Forms.Label
$script:LblVerifySelection.Text = ''
$script:LblVerifySelection.Location = New-Object System.Drawing.Point(14, 140)
$script:LblVerifySelection.Size = New-Object System.Drawing.Size(860, 20)
$script:LblVerifySelection.Font = $fontSmall
$script:LblVerifySelection.ForeColor = $grey
$grpVerify.Controls.Add($script:LblVerifySelection)

$lblVerifyNote = New-Object System.Windows.Forms.Label
$lblVerifyNote.Text = '「官方」这一列是发版时写进管理器的固定值；「本机实际」在每次启动、以及点「重新校验」时重算。两者不一样，就说明这个文件不是官方发布的那一份。'
$lblVerifyNote.Location = New-Object System.Drawing.Point(14, 186)
$lblVerifyNote.Size = New-Object System.Drawing.Size(892, 34)
$lblVerifyNote.Font = $fontSmall
$lblVerifyNote.ForeColor = $grey
$tabVerify.Controls.Add($lblVerifyNote)

$btnVerify = New-Object System.Windows.Forms.Button
$btnVerify.Text = '重新校验'
$btnVerify.Location = New-Object System.Drawing.Point(14, 228)
$btnVerify.Size = New-Object System.Drawing.Size(120, 30)
$btnVerify.FlatStyle = 'Flat'
$tabVerify.Controls.Add($btnVerify)

$lblVerifyState = New-Object System.Windows.Forms.Label
$lblVerifyState.Text = ''
$lblVerifyState.Location = New-Object System.Drawing.Point(146, 234)
$lblVerifyState.Size = New-Object System.Drawing.Size(760, 20)
$lblVerifyState.Font = $fontSmall
$lblVerifyState.ForeColor = $grey
$tabVerify.Controls.Add($lblVerifyState)

$grpChannels = New-Object PaletteGroupBox
$grpChannels.Text = '官方渠道'
$grpChannels.Location = New-Object System.Drawing.Point(14, 268)
$grpChannels.Size = New-Object System.Drawing.Size(892, 80)
$grpChannels.Font = $font
$tabVerify.Controls.Add($grpChannels)

$lblChannelUrl = New-Object System.Windows.Forms.Label
$lblChannelUrl.Text = ('项目主页：{0}' -f $script:ProjectUrl)
$lblChannelUrl.Location = New-Object System.Drawing.Point(14, 24)
$lblChannelUrl.Size = New-Object System.Drawing.Size(860, 20)
$lblChannelUrl.Font = $fontSmall
$lblChannelUrl.ForeColor = $grey
$grpChannels.Controls.Add($lblChannelUrl)

$lblChannelQq = New-Object System.Windows.Forms.Label
$lblChannelQq.Text = ('交流群：QQ {0}（免费使用；遇到问题、想反馈都可以来群里说）' -f $script:QqGroup)
$lblChannelQq.Location = New-Object System.Drawing.Point(14, 48)
$lblChannelQq.Size = New-Object System.Drawing.Size(860, 20)
$lblChannelQq.Font = $fontSmall
$lblChannelQq.ForeColor = $grey
$grpChannels.Controls.Add($lblChannelQq)

$btnVerify.Add_Click({
    $headline = Invoke-IntegrityCheck
    $lblVerifyState.Text = ('校验完成 {0} · {1}' -f (Get-Date -Format 'HH:mm:ss'), $headline.Text)
    $lblVerifyState.ForeColor = switch ($headline.Level) {
        'bad'   { $script:Red }
        'warn'  { $script:Amber }
        default { $script:Sage }
    }
})

# --- status ----------------------------------------------------------------

$status = New-Object System.Windows.Forms.Label
$status.Location = New-Object System.Drawing.Point(24, ($tabs.Top + $tabs.Height + 6))
$status.Size = New-Object System.Drawing.Size(916, 26)
$status.ForeColor = [System.Drawing.Color]::FromArgb(60, 60, 60)
$form.Controls.Add($status)

# --- free / open-source footer ---------------------------------------------
#
# Permanent, unlike the first-run dialog: this is the line a buyer sees while
# the software is open, on every page, without having to click anything. The
# whole line is one link that opens the statement.

$noticeLink = New-Object System.Windows.Forms.LinkLabel
$noticeLink.Text = ('免费开源 · 唯一官方来源 {0} · 交流群 {1} · 付费购买请联系退款（点此查看声明）' -f
    $script:ProjectUrl.Replace('https://', ''), $script:QqGroup)
$noticeLink.Font = $fontSmall
$noticeLink.LinkBehavior = [System.Windows.Forms.LinkBehavior]::HoverUnderline
$noticeLink.TabStop = $false
$noticeLink.AutoSize = $false
$noticeLink.Location = New-Object System.Drawing.Point(24, ($status.Top + $status.Height))
$noticeLink.Size = New-Object System.Drawing.Size(916, 20)
$noticeLink.Add_LinkClicked({ Show-ProjectNotice })
$form.Controls.Add($noticeLink)

# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

function Update-Status {
    param([string]$Message, [string]$Kind = 'info')

    $status.Text = $Message
    switch ($Kind) {
        'ok'   { $status.ForeColor = $sage }
        'err'  { $status.ForeColor = $red }
        'busy' { $status.ForeColor = $amber }
        default { $status.ForeColor = $script:Grey }
    }
    $status.Refresh()
}

# Read the text currently in a custom editor, whatever kind it is.
function Get-CustomEditorText {
    param([string]$Key)

    $entry = $script:CustomEditors[$Key]
    if (-not $entry) { return '' }
    return $entry.Editor.Text.Trim()
}

# Select the 自定义 entry of `key`'s dropdown, if it has one.
function Select-CustomChoice {
    param([string]$Key)

    $choices = $script:SettingDefs[$Key].Choices
    for ($i = 0; $i -lt $choices.Count; $i++) {
        if ($choices[$i].Value -eq 'custom') {
            $script:Controls[$Key].SelectedIndex = $i
            return
        }
    }
}

# Enable each custom editor only while its own dropdown sits on 自定义.
function Update-CustomEnabled {
    foreach ($key in $script:CustomEditors.Keys) {
        $customIndex = -1
        $choices = $script:SettingDefs[$key].Choices
        for ($i = 0; $i -lt $choices.Count; $i++) {
            if ($choices[$i].Value -eq 'custom') { $customIndex = $i; break }
        }
        $on = ($script:Controls[$key].SelectedIndex -eq $customIndex)
        $entry = $script:CustomEditors[$key]
        $entry.Editor.Enabled = $on
        if ($entry.Label) { $entry.Label.Enabled = $on }
        if ($entry.Unit) { $entry.Unit.Enabled = $on }
    }
}

# The same thing, read out of the live controls.
function Get-WindowSizeText {
    $family = [string]$script:SettingDefs['window_family'].Default
    $scale = [string]$script:SettingDefs['window_scale'].Default

    if ($script:Controls.ContainsKey('window_family')) {
        $c = $script:Controls['window_family']
        if ($c.SelectedIndex -ge 0) {
            $family = $script:SettingDefs['window_family'].Choices[$c.SelectedIndex].Value
        }
    }
    if ($script:Controls.ContainsKey('window_scale')) {
        $c = $script:Controls['window_scale']
        if ($c.SelectedIndex -ge 0) {
            $scale = $script:SettingDefs['window_scale'].Choices[$c.SelectedIndex].Value
        }
        if ($scale -eq 'custom') { $scale = Get-CustomEditorText -Key 'window_scale' }
    }

    return Get-WindowSizeForScale -Family $family -Scale $scale
}

function Update-WindowSizeLabel {
    if (-not $script:LblWindowSize) { return }

    $text = Get-WindowSizeText
    $script:LblWindowSize.Text = "窗口 $text"

    # Turn the readout red when the window would not fit the screen, since this
    # is the one place the user can see that before launching.
    $fits = $true
    if ($text -match '^窗口 (\d+) × (\d+)$') {
        $wa = [System.Windows.Forms.Screen]::FromControl($form).WorkingArea
        $fits = ([int]$Matches[1] -le $wa.Width) -and ([int]$Matches[2] -le $wa.Height)
    }
    $script:LblWindowSize.ForeColor = if ($fits) { $sage } else { $amber }
}

# Periodic resync for state that SelectedIndexChanged cannot be trusted to report.
#
# WinForms raises SelectedIndexChanged when the user picks an item, but NOT when
# the selection is changed by other means (the CB_SETCURSEL message, or a
# programmatic assignment that bypasses the event). Three things depend on that:
#
#   * the custom editors' enabled state (their dropdowns)
#   * the window-size readout (both window dropdowns)
#   * which app id / save folder is in force (IPA dropdown)
#
# A cheap periodic check removes the whole class of bug, and makes the UI testable
# by driving the controls with messages instead of synthetic mouse input.
$script:UiTimer = New-Object System.Windows.Forms.Timer
$script:UiTimer.Interval = 250
$script:UiTimer.Add_Tick({
    try {
        if (-not $script:UiReady) { return }

        # 1. custom editors' enabled state
        foreach ($key in $script:CustomEditors.Keys) {
            $customIndex = -1
            $choices = $script:SettingDefs[$key].Choices
            for ($i = 0; $i -lt $choices.Count; $i++) {
                if ($choices[$i].Value -eq 'custom') { $customIndex = $i; break }
            }
            $should = ($script:Controls[$key].SelectedIndex -eq $customIndex)
            if ($script:CustomEditors[$key].Editor.Enabled -ne $should) { Update-CustomEnabled }
        }

        # 2. window-size readout
        Update-WindowSizeLabel

        # 3. IPA selection: if the dropdown no longer matches the id in force,
        #    apply it. This is what makes switching work regardless of how the
        #    selection was changed.
        $sel = $cmbIpa.SelectedIndex
        if ($sel -ge 0 -and $sel -lt $script:IpaEntries.Count) {
            $entry = $script:IpaEntries[$sel]
            if ($entry.Path -ne $script:CurrentIpa.Path) {
                Apply-IpaSelection -IpaInfo $entry -Persist
            }
        }
    } catch {
        # Never let a resync failure take down the UI loop.
    }
})
$script:UiTimer.Start()

function Update-SimulatedTimeLabel {
    try {
        $offset = Read-TimeOffset
        $btnResetTime.Visible = $offset -ne 0
        $clock = Format-SimulatedTime -Offset $offset -Base (Get-SimulatedTimeBase)
        $lblSimulatedTime.Text = "模拟时间：$clock"
    } catch {
        $btnResetTime.Visible = $true
        $lblSimulatedTime.Text = '模拟时间：无法读取（请检查累计时间偏移）'
    }
}

$btnResetTime.Add_Click({
    if (Test-GameRunning) {
        Update-Status '游戏正在运行，请先退出游戏再重置模拟时间。' 'err'
        return
    }
    $answer = [System.Windows.Forms.MessageBox]::Show(
        '将清除累计快进时间，模拟时间恢复到当前时间，不会修改游戏存档。',
        '重置为当前时间？', 'YesNo', 'Question')
    if ($answer -ne 'Yes') { return }
    try {
        Write-TimeOffset -Value 0
        Update-SimulatedTimeLabel
        Update-Status '模拟时间已重置。' 'ok'
    } catch {
        Update-Status ("重置模拟时间失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '重置失败', 'OK', 'Error')
    }
})

$clockTimer = New-Object System.Windows.Forms.Timer
$clockTimer.Interval = 1000
$clockTimer.Add_Tick({ if ($tabs.SelectedTab -eq $tabGame) { Update-SimulatedTimeLabel } })
$form.Add_Shown({ Update-SimulatedTimeLabel; $clockTimer.Start() })
$tabs.Add_SelectedIndexChanged({ if ($tabs.SelectedTab -eq $tabGame) { Update-SimulatedTimeLabel } })

function Load-SettingsIntoUi {
    $grpSettings.Enabled = [bool]$script:AppId
    $settings = Get-CurrentSettings
    foreach ($key in $script:SettingDefs.Keys) {
        $def = $script:SettingDefs[$key]
        $value = [string]$settings[$key]

        $index = -1
        for ($i = 0; $i -lt $def.Choices.Count; $i++) {
            if ($def.Choices[$i].Value -eq $value) { $index = $i; break }
        }

        if ($def.AllowCustom) {
            $entry = $script:CustomEditors[$key]
            if ($entry) {
                # Discard a draft from the previous IPA when loading a preset.
                $entry.Editor.Text = if ($index -lt 0) { $value } else { [string]$def.CustomInitial }
            }
        }
        if ($index -lt 0 -and $def.AllowCustom) {
            for ($i = 0; $i -lt $def.Choices.Count; $i++) {
                if ($def.Choices[$i].Value -eq 'custom') { $index = $i; break }
            }
        }
        if ($index -lt 0) { $index = 0 }

        $script:Controls[$key].SelectedIndex = $index
    }
    Update-CustomEnabled
    Update-WindowSizeLabel
}

function Refresh-Currency {
    $c = Get-Currency
    if ($c) {
        $numGold.Text = [string][Math]::Min([int64]$c.Gold, [int64]2147483647)
        $numBrains.Text = [string][Math]::Min([int64]$c.Brains, [int64]2147483647)
        $lblCurrencyState.Text = "当前存档：金币 $($c.Gold)　脑子 $($c.Brains)"
        $lblCurrencyState.ForeColor = $grey
        $btnApplyCurrency.Enabled = $true
    } else {
        $lblCurrencyState.Text = '读不到存档（文件不存在或格式不符）'
        $lblCurrencyState.ForeColor = $red
        $btnApplyCurrency.Enabled = $false
    }
}

function Update-SaveTab {
    $listSaves.BeginUpdate()
    $listSaves.Items.Clear()

    $hadLive = $script:LiveSave -and (Test-Path -LiteralPath $script:LiveSave)
    if (-not $hadLive) {
        $lblSaveInfo.Text = '找不到当前存档。'
        $lblSaveInfo.ForeColor = $red
    } else {
        $live = Get-Item -LiteralPath $script:LiveSave
        $lblSaveInfo.Text = ("当前存档：saveGame.bin2　{0} 字节　{1}" -f `
            $live.Length, $live.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))
        $lblSaveInfo.ForeColor = $grey
    }

    # The live save is listed first and marked, because "which save is actually in
    # use?" is the question this tab has to answer at a glance. It is not a
    # backup: restoring and deleting are refused for it.
    if ($hadLive) {
        $live = Get-Item -LiteralPath $script:LiveSave
        $item = New-Object System.Windows.Forms.ListViewItem('正在使用')
        [void]$item.SubItems.Add($live.Name)
        [void]$item.SubItems.Add([string]$live.Length)
        [void]$item.SubItems.Add($live.LastWriteTime.ToString('MM-dd HH:mm'))
        $item.Tag = $live.FullName
        $item.ForeColor = $script:Sage
        $item.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 8.5, [System.Drawing.FontStyle]::Bold)
        [void]$listSaves.Items.Add($item)
    }

    $files = Get-BackupFiles
    foreach ($f in $files) {
        $kind = Get-BackupKind -File $f
        $item = New-Object System.Windows.Forms.ListViewItem($kind)
        [void]$item.SubItems.Add($f.Name)
        [void]$item.SubItems.Add([string]$f.Length)
        [void]$item.SubItems.Add($f.LastWriteTime.ToString('MM-dd HH:mm'))
        $item.Tag = $f.FullName
        [void]$listSaves.Items.Add($item)
    }
    $listSaves.EndUpdate()

    $size = 0
    foreach ($f in $files) { $size += $f.Length }
    $lblSaveHint.Text = ("共 {0} 个备份，{1:N1} KB" -f $files.Count, ($size / 1KB))
    Update-SelectionCount
}

# Selection feedback for the bulk buttons.
function Update-SelectionCount {
    $n = $listSaves.SelectedItems.Count
    $total = $listSaves.Items.Count
    if ($total -eq 0) { return }
    $lblSaveHint.Text = "已选 $n / $total 个备份"
}

# The live save is not a backup: refuse to restore or delete it through the UI.
function Test-IsLiveSave {
    param([string]$Path)
    return $Path -eq $script:LiveSave
}

# Restore operates on exactly one row. Multi-select exists for deleting, so take
# the first selection and say so if several rows happen to be selected.
function Get-SelectedBackup {
    if ($listSaves.SelectedItems.Count -eq 0) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '请先在列表里选择一个备份。', '存档管理', 'OK', 'Information')
        return $null
    }
    if ($listSaves.SelectedItems.Count -gt 1) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '还原一次只能选一个备份。请只选中要还原的那一个。', '存档管理', 'OK', 'Information')
        return $null
    }
    return [string]$listSaves.SelectedItems[0].Tag
}

# Every selected row that is a real backup (never the live save).
function Get-SelectedBackups {
    $paths = @()
    foreach ($item in $listSaves.SelectedItems) {
        $p = [string]$item.Tag
        if (Test-IsLiveSave -Path $p) { continue }
        $paths += $p
    }
    return $paths
}

# Human-readable name for a setting, for the status line. A setting that shares a
# row (window_scale) has an empty Label of its own, so it falls back to its own
# name rather than reporting a blank.
function Get-SettingTitle {
    param([string]$Key)

    $def = $script:SettingDefs[$Key]
    if ($def.Label) { return $def.Label }
    switch ($Key) {
        'window_scale' { return '放大倍数' }
        'window_family' { return '窗口大小 / 分辨率' }
        default { return $Key }
    }
}

# Settings are persisted the moment they change: there is no OK/Apply button, so
# closing the window can never silently discard an edit.
$onSettingChanged = {
    param($sender, $eventArgs)

    if ($sender.SelectedIndex -lt 0) { return }
    if (-not $script:UiReady) { return }

    $key = [string]$sender.Tag
    try {
        Update-CustomEnabled
        Update-WindowSizeLabel
        $def = $script:SettingDefs[$key]
        $value = $def.Choices[$sender.SelectedIndex].Value
        $shown = $def.Choices[$sender.SelectedIndex].Text
        if ($value -eq 'custom') {
            $value = Get-CustomEditorText -Key $key
            if (-not (Test-SettingValue -Key $key -Value $value)) {
                Update-Status ("{0} 的值 '{1}' 无效，尚未保存。" -f (Get-SettingTitle -Key $key), $value) 'busy'
                return
            }
            $shown = $value
            if ($def.ContainsKey('CustomSuffix') -and $def.CustomSuffix) {
                $shown = "$shown $($def.CustomSuffix)"
            }
        }
        Save-Settings -Settings @{ $key = $value }
        Update-Status ("已保存：{0} = {1}" -f (Get-SettingTitle -Key $key), $shown) 'ok'
    } catch {
        Update-Status ("保存失败：{0}" -f $_.Exception.Message) 'err'
    }
}

# A custom editor is part of its setting's value, so any edit to it must be saved
# too - not just a dropdown change.
#
# For the text-based scale editor the value is only written once it is complete
# and valid: an intermediate "1." or "7/" is not a scale touchHLE could parse, and
# persisting it would leave the options file in a state the game refuses to start
# from. TextBox gives no "editing finished" event worth relying on (Leave fires
# on focus change only), so validation happens here on every keystroke and the
# file is simply left alone until the text is valid.
$onCustomEditorChanged = {
    param($sender, $eventArgs)

    if (-not $script:UiReady) { return }

    $key = [string]$sender.Tag
    $entry = $script:CustomEditors[$key]
    if (-not $entry -or -not $entry.Editor.Enabled) { return }

    $text = Get-CustomEditorText -Key $key
    if (-not (Test-SettingValue -Key $key -Value $text)) {
        # Not (yet) a value touchHLE accepts: say so and keep the file as it was.
        # (Plain ASCII quotes: PowerShell 5.1 treats the curly “ ” as string
        # delimiters even inside a double-quoted string, which is a parse error.)
        Update-Status ("{0} 的值 '{1}' 无效，尚未保存。" -f (Get-SettingTitle -Key $key), $text) 'busy'
        return
    }

    try {
        Update-WindowSizeLabel
        Save-Settings -Settings @{ $key = $text }
        $shown = $text
        if ($script:SettingDefs[$key].ContainsKey('CustomSuffix') -and $script:SettingDefs[$key].CustomSuffix) {
            $shown = "$text $($script:SettingDefs[$key].CustomSuffix)"
        }
        Update-Status ("已保存：{0} = {1}" -f (Get-SettingTitle -Key $key), $shown) 'ok'
    } catch {
        Update-Status ("保存失败：{0}" -f $_.Exception.Message) 'err'
    }
}

foreach ($key in $script:SettingDefs.Keys) {
    $script:Controls[$key].Add_SelectedIndexChanged($onSettingChanged)
}
foreach ($key in $script:CustomEditors.Keys) {
    $entry = $script:CustomEditors[$key]
    # Intermediate numeric text is validated before it is written.
    $entry.Editor.Add_TextChanged($onCustomEditorChanged)
}

# --- launching -------------------------------------------------------------
#
# Self-contained: this does NOT call StartZombieFarmNextHour.ps1. The launcher
# logic (IPA path, cumulative time offset, the -Quiet no-console trick) is
# reproduced here so the manager is a single file with no helper-script
# dependency. The steps are kept identical to the original on purpose:
#
#   1. read the cumulative offset from touchHLE_time_offset_seconds.txt
#   2. add this run's increment (skipped when the user chose not to skip)
#   3. write the offset file back
#   4. export TOUCHHLE_TIME_OFFSET_SECONDS
#   5. write zfr_last_launch.txt with the IPA fingerprint
#   6. start touchHLE.exe with CreateNoWindow so no console is allocated
#
# touchHLE.exe is a CONSOLE-subsystem program, so letting it inherit a console
# would pop up the very black window this UI exists to avoid.
#
# Get-LaunchPaths lives near the top of the file, with the other helpers.

# Start the game and block until it exits.
#
#   -SkipSeconds 0 means "do not advance the clock", otherwise the cumulative
#   offset is increased by that many seconds.
function Start-GameProcess {
    param(
        [Parameter(Mandatory = $true)][int64]$SkipSeconds,
        [Parameter(Mandatory = $true)][string]$BusyMessage
    )

    $paths = Get-LaunchPaths

    if (-not (Test-Path -LiteralPath $paths.TouchHLE)) {
        throw "找不到 touchHLE.exe：$($paths.TouchHLE)"
    }
    $integrity = Invoke-IntegrityCheck
    if (-not $paths.Ipa -or -not (Test-Path -LiteralPath $paths.Ipa -PathType Leaf)) {
        $hint = "请选择一个可用的 IPA，或从项目主页重新下载整合包。`r`n$($script:ProjectUrl)"
        if ($integrity.Level -ne 'ok') { throw ($integrity.Text + "`r`n`r`n" + $hint) }
        throw ("找不到所选的游戏 IPA。`r`n`r`n" + $hint)
    }
    if ($integrity.Level -ne 'ok') {
        Write-ManagerLog ('integrity check: {0}' -f $integrity.Text)
        $answer = [System.Windows.Forms.MessageBox]::Show($form,
            ($integrity.Text + "`r`n`r`n项目主页：$($script:ProjectUrl)`r`n`r`n继续启动所选的 IPA 吗？"),
            '文件校验', 'YesNo', 'Warning')
        if ($answer -ne 'Yes') { return }
    }

    Update-Status $BusyMessage 'busy'
    $form.Hide()

    # The log belongs beside touchHLE's other state, not in the parent folder.
    $logFile = Join-Path $script:HleDir 'zfr_last_run.log'
    $started = Get-Date
    $proc = $null
    try {
        $proc = New-GameChildProcess -Paths $paths -SkipSeconds $SkipSeconds
    } catch {
        $form.Show()
        $form.Activate()
        throw
    }

    # Drain both pipes concurrently; reading them one after the other can deadlock
    # if the child fills the second pipe's buffer while we block on the first.
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()

    # Wait in slices rather than one blind WaitForExit(): a crash can leave the
    # process alive with its window gone, and then this method never returns and
    # the manager never comes back -- the state players described as "the game
    # says it is running, but there is nothing running".
    $seenWindow = $false
    $windowlessSince = $null
    $offeredRecovery = $false
    $endedByManager = $false
    $slice = 0
    while ($true) {
        $exited = $false
        try { $exited = $proc.WaitForExit(500) } catch { $exited = $true }
        if ($exited) { break }
        try { if ($proc.HasExited) { break } } catch { break }

        $slice++
        # Sampling window handles is cheap but not free; every fourth slice is plenty.
        if (($slice % 4) -ne 0) { continue }
        $hasWindow = $false
        try {
            $proc.Refresh()
            $hasWindow = ($proc.MainWindowHandle.ToInt64() -gt 0)
        } catch { }
        if ($hasWindow) {
            $seenWindow = $true
            $windowlessSince = $null
            continue
        }
        if ($null -eq $windowlessSince) { $windowlessSince = Get-Date }
        if ($offeredRecovery) { continue }

        # Offer recovery when a window that existed has been gone for a while, or
        # when a process that never opened one is clearly stalling.
        $silentFor = ((Get-Date) - $windowlessSince).TotalSeconds
        $stalledBeforeWindow = (-not $seenWindow) -and (((Get-Date) - $started).TotalSeconds -ge 120)
        if (-not (($seenWindow -and $silentFor -ge 20) -or $stalledBeforeWindow)) { continue }

        $offeredRecovery = $true
        Write-ManagerLog ('watchdog: pid={0} alive, no window for {1:N0}s (seenWindow={2})' -f $proc.Id, $silentFor, $seenWindow)
        $form.Show()
        $form.Activate()
        Update-Status '游戏窗口已消失，但进程仍在运行。' 'err'
        $answer = [System.Windows.Forms.MessageBox]::Show(
            ("游戏窗口已经消失，但 touchHLE.exe 仍在运行（PID {0}）。`n`n这通常是闪退后残留的进程：它不会自己退出，还会让管理器一直以为游戏在运行。`n`n结束它并回到管理器吗？（选「否」会继续等待它自行退出。）" -f $proc.Id),
            '游戏可能已崩溃', 'YesNo', 'Warning')
        if ($answer -eq 'Yes') {
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction Stop
                $endedByManager = $true
                Write-ManagerLog ('watchdog: user ended leftover pid={0}' -f $proc.Id)
            } catch {
                Write-ManagerLog ('watchdog: could not end pid={0}: {1}' -f $proc.Id, $_.Exception.Message)
            }
        } else {
            $form.Hide()
        }
    }

    # The timeout overload does not wait for the redirected readers; this one does.
    try { $proc.WaitForExit() } catch { }

    $out = ''; $err = ''
    try { $out = $outTask.Result } catch { }
    try { $err = $errTask.Result } catch { }

    $exitCode = $proc.ExitCode
    Remove-RunState
    Write-ManagerLog ('exit pid={0} code={1} after {2:N0}s' -f $proc.Id, $exitCode, ((Get-Date) - $started).TotalSeconds)

    if ($out -or $err) {
        $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $text = "[$stamp] exit=$exitCode`r`n$out`r`n$err`r`n"
        Add-Content -LiteralPath $logFile -Value $text -Encoding UTF8
    }

    $form.Show()
    $form.Activate()
    Refresh-Currency
    Update-SaveTab

    if ($endedByManager) {
        Update-Status '已结束残留的游戏进程。' 'ok'
    } elseif ($exitCode -eq 0) {
        Update-Status '游戏已退出。' 'info'
    } else {
        $panic = Get-PanicSummary -Text $err
        if ($panic) {
            Update-Status ("游戏异常退出：{0}" -f $panic) 'err'
        } else {
            Update-Status ("游戏异常退出：{0}（详见 zfr_last_run.log）" -f (Get-ExitCodeHint -Code $exitCode)) 'err'
        }
    }
}

$btnStart.Add_Click({
    if (-not (Confirm-NoRunningGame)) { return }
    try {
        Start-GameProcess -SkipSeconds 0 -BusyMessage '正在启动…'
    } catch {
        $form.Show()
        Update-Status ("启动失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message, '启动失败', 'OK', 'Error')
    }
})

$btnStartSkip.Add_Click({
    if (-not (Confirm-NoRunningGame)) { return }

    # Collect hours/minutes in two numeric boxes (no HH:MM string to type), in a
    # modal dialog rather than console input, so the UI never hands control back
    # to a terminal. Pre-fill from last time (Read-SkipMemory), default 6h00m.
    $mem = Read-SkipMemory
    $defH = if ($mem) { $mem.Hours } else { 6 }
    $defM = if ($mem) { $mem.Minutes } else { 0 }

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = '跳过时间'
    $dlg.ClientSize = New-Object System.Drawing.Size(344, 194)
    $dlg.StartPosition = 'CenterParent'
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.Font = $font
    $dlg.BackColor = $script:Paper
    $dlg.ForeColor = $script:Ink

    $l1 = New-Object System.Windows.Forms.Label
    $l1.Text = '快进多久？（只填数字）'
    $l1.Location = New-Object System.Drawing.Point(18, 16)
    $l1.AutoSize = $true
    $l1.ForeColor = $script:Ink
    $dlg.Controls.Add($l1)

    $numH = New-Object System.Windows.Forms.TextBox
    $numH.Location = New-Object System.Drawing.Point(20, 46)
    $numH.Size = New-Object System.Drawing.Size(96, 24)
    $numH.MaxLength = 4
    $numH.Text = [string][Math]::Min($defH, 9999)
    $numH.TextAlign = 'Center'
    $numH.BackColor = $script:Surface
    $numH.ForeColor = $script:Ink
    $dlg.Controls.Add($numH)
    $numH.Add_KeyPress({ if (-not [char]::IsControl($_.KeyChar) -and -not [char]::IsDigit($_.KeyChar)) { $_.Handled = $true } })

    $lH = New-Object System.Windows.Forms.Label
    $lH.Text = '小时'
    $lH.Location = New-Object System.Drawing.Point(122, 49)
    $lH.AutoSize = $true
    $lH.ForeColor = $script:Ink
    $dlg.Controls.Add($lH)

    $numM = New-Object System.Windows.Forms.TextBox
    $numM.Location = New-Object System.Drawing.Point(180, 46)
    $numM.Size = New-Object System.Drawing.Size(80, 24)
    $numM.MaxLength = 2
    $numM.Text = [string]$defM
    $numM.TextAlign = 'Center'
    $numM.BackColor = $script:Surface
    $numM.ForeColor = $script:Ink
    $dlg.Controls.Add($numM)
    $numM.Add_KeyPress({ if (-not [char]::IsControl($_.KeyChar) -and -not [char]::IsDigit($_.KeyChar)) { $_.Handled = $true } })

    $lM = New-Object System.Windows.Forms.Label
    $lM.Text = '分钟'
    $lM.Location = New-Object System.Drawing.Point(266, 49)
    $lM.AutoSize = $true
    $lM.ForeColor = $script:Ink
    $dlg.Controls.Add($lM)

    $preview = New-Object System.Windows.Forms.Label
    $preview.Location = New-Object System.Drawing.Point(20, 82)
    $preview.Size = New-Object System.Drawing.Size(310, 54)
    $dlg.Controls.Add($preview)

    $okBtn = New-Object System.Windows.Forms.Button
    $okBtn.Text = '开始'
    $okBtn.Location = New-Object System.Drawing.Point(142, 144)
    $okBtn.Size = New-Object System.Drawing.Size(86, 30)
    $okBtn.DialogResult = 'OK'
    $okBtn.FlatStyle = 'Flat'
    $okBtn.BackColor = $script:Forest
    $okBtn.ForeColor = [System.Drawing.Color]::White
    $okBtn.FlatAppearance.BorderSize = 0
    $dlg.Controls.Add($okBtn)

    $cancelBtn = New-Object System.Windows.Forms.Button
    $cancelBtn.Text = '取消'
    $cancelBtn.Location = New-Object System.Drawing.Point(238, 144)
    $cancelBtn.Size = New-Object System.Drawing.Size(86, 30)
    $cancelBtn.DialogResult = 'Cancel'
    $cancelBtn.FlatStyle = 'Flat'
    $cancelBtn.BackColor = $script:SoftGreen
    $cancelBtn.ForeColor = $script:Forest
    $cancelBtn.FlatAppearance.BorderSize = 0
    $dlg.Controls.Add($cancelBtn)

    $dlg.AcceptButton = $okBtn
    $dlg.CancelButton = $cancelBtn

    $updatePreview = {
        $current = '无法读取'
        $after = '请输入有效的快进时间'
        $okBtn.Enabled = $false
        try {
            $base = Get-SimulatedTimeBase
            $offset = Read-TimeOffset
            $current = Format-SimulatedTime -Offset $offset -Base $base
            if ($numH.Text.Trim() -match '^[0-9]{1,4}$' -and $numM.Text.Trim() -match '^[0-9]{1,2}$') {
                $hours = [int]$numH.Text.Trim()
                $minutes = [int]$numM.Text.Trim()
                if ($minutes -le 59 -and ($hours -gt 0 -or $minutes -gt 0)) {
                    $after = Format-SimulatedTime -Offset ($offset + $hours * 3600 + $minutes * 60) -Base $base
                    $okBtn.Enabled = $true
                }
            }
        } catch {
            $after = '模拟时间不可用或超出游戏支持范围'
        }
        $preview.Text = "当前模拟时间：$current" + [Environment]::NewLine + "快进后：$after"
    }
    $numH.Add_TextChanged($updatePreview)
    $numM.Add_TextChanged($updatePreview)
    $previewTimer = New-Object System.Windows.Forms.Timer
    $previewTimer.Interval = 1000
    $previewTimer.Add_Tick($updatePreview)
    & $updatePreview
    $previewTimer.Start()
    try { $result = $dlg.ShowDialog($form) } finally { $previewTimer.Dispose() }
    $hoursText = $numH.Text.Trim()
    $minutesText = $numM.Text.Trim()
    $dlg.Dispose()
    if ($result -ne 'OK') { return }

    if ($hoursText -notmatch '^[0-9]{1,4}$' -or $minutesText -notmatch '^[0-9]{1,2}$') {
        [void][System.Windows.Forms.MessageBox]::Show('请输入有效的小时和分钟。', '跳过时间', 'OK', 'Warning')
        return
    }
    $hours = [int]$hoursText
    $minutes = [int]$minutesText
    if ($minutes -gt 59) {
        [void][System.Windows.Forms.MessageBox]::Show('分钟必须在 0～59 之间。', '跳过时间', 'OK', 'Warning')
        return
    }

    if ($hours -le 0 -and $minutes -le 0) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '总时间要大于零。', '跳过时间', 'OK', 'Warning')
        return
    }

    try {
        Save-SkipMemory -Hours $hours -Minutes $minutes
        $skipSeconds = ([int64]$hours * 3600) + ([int64]$minutes * 60)
        Start-GameProcess -SkipSeconds $skipSeconds `
            -BusyMessage ("正在启动（快进 {0} 小时 {1} 分）…" -f $hours, $minutes)
    } catch {
        $form.Show()
        Update-Status ("启动失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message, '启动失败', 'OK', 'Error')
    }
})

# --- save management -------------------------------------------------------

$btnBackup.Add_Click({
    if (Test-GameRunning) {
        Update-Status '游戏正在运行，请先关闭游戏再备份存档。' 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            '游戏正在运行。存档只在正常退出时写入，现在备份可能拿到不完整的状态。请先关闭游戏。',
            '无法备份', 'OK', 'Warning')
        return
    }
    try {
        $made = New-SaveBackup -Label 'manual'
        Update-SaveTab
        Update-Status ("已备份：{0}" -f [System.IO.Path]::GetFileName($made)) 'ok'
    } catch {
        Update-Status ("备份失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '备份失败', 'OK', 'Error')
    }
})

$btnRestore.Add_Click({
    $path = Get-SelectedBackup
    if (-not $path) { return }

    # The live save is shown in the list for reference but cannot be "restored"
    # onto itself.
    if (Test-IsLiveSave -Path $path) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '这是正在使用的存档本身，不是备份。请选择一条备份来还原。',
            '存档管理', 'OK', 'Information')
        return
    }
    if (Test-GameRunning) {
        Update-Status '游戏正在运行，请先关闭游戏再还原存档。' 'err'
        return
    }

    $name = [System.IO.Path]::GetFileName($path)
    $size = (Get-Item -LiteralPath $path).Length
    $answer = [System.Windows.Forms.MessageBox]::Show(
        ("要用这个备份覆盖当前存档吗？`n`n{0}`n{1} 字节`n`n当前存档会先自动另存为一份，所以可以反悔。" -f $name, $size),
        '还原备份', 'YesNo', 'Question')
    if ($answer -ne 'Yes') { return }

    try {
        [void](Restore-SaveBackup -BackupPath $path)
        Update-SaveTab
        Refresh-Currency
        Update-Status ("已还原：{0}" -f $name) 'ok'
    } catch {
        Update-Status ("还原失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '还原失败', 'OK', 'Error')
    }
})

$btnDelete.Add_Click({
    $paths = Get-SelectedBackups
    if ($paths.Count -eq 0) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '请先在列表里选择要删除的备份。', '存档管理', 'OK', 'Information')
        return
    }

    if ($paths.Count -eq 1) {
        $name = [System.IO.Path]::GetFileName($paths[0])
        $question = "确定删除这个备份吗？删掉就找不回来了。`n`n$name"
    } else {
        # Show a few names so a mis-click on "select all" is obvious before it is
        # too late, rather than just asking "delete 31 items?".
        $preview = ($paths | Select-Object -First 5 | ForEach-Object { [System.IO.Path]::GetFileName($_) }) -join "`n"
        if ($paths.Count -gt 5) { $preview += "`n… 等共 $($paths.Count) 个" }
        $question = "确定删除这 $($paths.Count) 个备份吗？删掉就找不回来了。`n`n$preview"
    }

    $answer = [System.Windows.Forms.MessageBox]::Show(
        $question, '删除备份', 'YesNo', 'Warning')
    if ($answer -ne 'Yes') { return }

    $done = 0
    $failed = @()
    foreach ($p in $paths) {
        try {
            [void](Remove-SaveBackup -BackupPath $p)
            $done++
        } catch {
            $failed += ("{0}: {1}" -f [System.IO.Path]::GetFileName($p), $_.Exception.Message)
        }
    }

    Update-SaveTab
    if ($failed.Count -eq 0) {
        Update-Status ("已删除 {0} 个备份。" -f $done) 'ok'
    } else {
        Update-Status ("已删除 {0} 个，{1} 个失败。" -f $done, $failed.Count) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            ("以下备份删除失败：`n`n" + ($failed -join "`n")), '部分失败', 'OK', 'Warning')
    }
})

$btnRefresh.Add_Click({
    Update-SaveTab
    Refresh-Currency
    Update-Status '已刷新。' 'info'
})

$btnSelectAll.Add_Click({
    foreach ($item in $listSaves.Items) { $item.Selected = $true }
    Update-SelectionCount
})

$btnSelectNone.Add_Click({
    foreach ($item in $listSaves.Items) { $item.Selected = $false }
    Update-SelectionCount
})

$btnSelectInvert.Add_Click({
    foreach ($item in $listSaves.Items) { $item.Selected = -not $item.Selected }
    Update-SelectionCount
})

$listSaves.Add_ItemSelectionChanged({
    Update-SelectionCount
    $listSaves.Invalidate()
})

$listSaves.Add_DoubleClick({
    if ($listSaves.SelectedItems.Count -gt 0) { $btnRestore.PerformClick() }
})

# --- currency --------------------------------------------------------------

$btnApplyCurrency.Add_Click({
    if (Test-GameRunning) {
        [void][System.Windows.Forms.MessageBox]::Show(
            '游戏正在运行。存档只在正常退出时写入，现在修改会被覆盖。请先关闭游戏。',
            '无法修改', 'OK', 'Warning')
        Update-Status '游戏正在运行，请先关闭游戏再改存档。' 'err'
        return
    }

    $goldText = $numGold.Text.Trim()
    $brainsText = $numBrains.Text.Trim()
    if ($goldText -notmatch '^[0-9]{1,10}$' -or $brainsText -notmatch '^[0-9]{1,10}$') {
        Update-Status '金币和脑子必须是 0～2147483647 的整数。' 'err'
        return
    }
    $gold64 = [int64]$goldText
    $brains64 = [int64]$brainsText
    if ($gold64 -gt 2147483647 -or $brains64 -gt 2147483647) {
        Update-Status '金币和脑子不能超过 2147483647。' 'err'
        return
    }
    $gold = [int]$gold64
    $brains = [int]$brains64

    $answer = [System.Windows.Forms.MessageBox]::Show(
        ("将把存档改为：`n`n金币 $gold`n脑子 $brains`n`n原存档会自动备份。继续吗？"),
        '确认修改', 'YesNo', 'Question')
    if ($answer -ne 'Yes') { return }

    try {
        # Self-contained writer; no helper script involved.
        $backupPath = Set-Currency -Gold $gold -Brains $brains
        Update-Status ("存档已更新，备份：{0}" -f [System.IO.Path]::GetFileName($backupPath)) 'ok'
        Refresh-Currency
        Update-SaveTab
    } catch {
        Update-Status ("写入失败：{0}" -f $_.Exception.Message) 'err'
        [void][System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message, '写入失败', 'OK', 'Error')
    }
})

# --- IPA selection behaviour -----------------------------------------------

# Fill the dropdown from zombie_farm_ipa\, remembering the detected bundle id for the
# entry currently chosen so the settings/save paths can be re-pointed.
$script:IpaEntries = @()

function Update-IpaInfoLabel {
    if ($null -eq $script:CurrentIpa) {
        $lblIpaInfo.Text = '未选择任何 IPA。'
        $lblIpaInfo.ForeColor = $red
        return
    }
    $info = $script:CurrentIpa
    if ($info.Error) {
        $lblIpaInfo.Text = "⚠ $($info.Error)　无法管理此 IPA 的设置和存档"
        $lblIpaInfo.ForeColor = $red
        return
    }
    $sizeMb = [Math]::Round($info.Size / 1MB, 1)
    $lblIpaInfo.Text = ("app id: {0}　可执行文件: {1}　{2} MB" -f `
        $script:AppId, $info.Executable, $sizeMb)
    $lblIpaInfo.ForeColor = $grey
}

# Point every app-id-dependent path at the chosen IPA and refresh the views that
# depend on it (the saves and settings both live under the app id).
function Apply-IpaSelection {
    param(
        [Parameter(Mandatory = $true)]$IpaInfo,
        [switch]$Persist
    )

    $previousId = $script:AppId
    Set-CurrentIpa -IpaInfo $IpaInfo

    Update-IpaInfoLabel
    if ($script:UiReady) {
        Update-IntegrityDisplay
        if ($script:AppId -cne $previousId) {
            $script:UiReady = $false
            try {
                Load-SettingsIntoUi
            } finally {
                $script:UiReady = $true
            }
        }
        Refresh-Currency
        Update-SaveTab
    }
    if ($Persist) { Save-IpaSelection -Path $IpaInfo.Path }
}

function Initialize-IpaList {
    $script:IpaEntries = @()
    $wanted = Get-DefaultIpaPath
    $files = @(Get-IpaList)
    if ($wanted -and $files.FullName -notcontains $wanted) {
        $files += Get-Item -LiteralPath $wanted
    }
    $idCounts = @{}
    foreach ($f in $files) {
        $info = Read-IpaInfo -Path $f.FullName
        $script:IpaEntries += $info
        $id = if ($info.AppId) { $info.AppId } else { '<未知>' }
        if (-not $idCounts.ContainsKey($id)) { $idCounts[$id] = 0 }
        $idCounts[$id]++
    }

    foreach ($info in $script:IpaEntries) {
        $id = if ($info.AppId) { $info.AppId } else { '<未知>' }
        # The dropdown is narrow, so only spell out the id where it is the odd one
        # out. With 29 files sharing one id, repeating it 29 times is noise, and
        # the minority id is exactly the case that changes saves and settings.
        $suffix = ''
        if ($idCounts[$id] -le 2) { $suffix = "　[$id]" }
        [void]$cmbIpa.Items.Add($info.Name + $suffix)
    }

    if ($script:IpaEntries.Count -eq 0) {
        $lblIpaInfo.Text = "在 $($script:IpaDir) 里找不到任何 .ipa 文件。"
        $lblIpaInfo.ForeColor = $red
        return
    }

    # Preselect the remembered/default IPA.
    $index = 0
    for ($i = 0; $i -lt $script:IpaEntries.Count; $i++) {
        if ($script:IpaEntries[$i].Path -eq $wanted) { $index = $i; break }
    }
    $cmbIpa.SelectedIndex = $index      # fires the handler below
}

$cmbIpa.Add_SelectedIndexChanged({
    if ($cmbIpa.SelectedIndex -lt 0) { return }
    if ($cmbIpa.SelectedIndex -ge $script:IpaEntries.Count) { return }

    $info = $script:IpaEntries[$cmbIpa.SelectedIndex]

    # Only re-point things (and repopulate lists) once the UI is live; during
    # construction this fires before the save tab exists.
    if (-not $script:UiReady) {
        Set-CurrentIpa -IpaInfo $info
        Update-IpaInfoLabel
        return
    }

    try {
        Apply-IpaSelection -IpaInfo $info -Persist
        Update-Status ("已选择：{0}" -f $info.Name) 'ok'
    } catch {
        Update-Status ("切换 IPA 失败：{0}" -f $_.Exception.Message) 'err'
    }
})

$btnIpaBrowse.Add_Click({
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = '选择游戏 IPA'
    $dlg.Filter = 'iOS 应用包 (*.ipa)|*.ipa|所有文件 (*.*)|*.*'
    $dlg.InitialDirectory = $script:IpaDir
    if ($dlg.ShowDialog($form) -ne 'OK') { $dlg.Dispose(); return }

    $chosen = $dlg.FileName
    $dlg.Dispose()

    $info = Read-IpaInfo -Path $chosen
    if ($info.Error) {
        [void][System.Windows.Forms.MessageBox]::Show(
            ("这个文件读不出 app id：`n`n{0}`n`n仍可尝试启动。识别出 app ID 后才能管理此游戏的设置和存档。" -f $info.Error),
            '提示', 'OK', 'Warning')
    }

    # If it came from the managed folder it is already in the list; otherwise add
    # it so the choice is visible and switchable.
    $index = -1
    for ($i = 0; $i -lt $script:IpaEntries.Count; $i++) {
        if ($script:IpaEntries[$i].Path -eq $chosen) { $index = $i; break }
    }
    if ($index -lt 0) {
        $label = '{0}　[{1}]' -f $info.Name, $(if ($info.AppId) { $info.AppId } else { '未知 id' })
        [void]$cmbIpa.Items.Add($label)
        $script:IpaEntries += $info
        $index = $script:IpaEntries.Count - 1
    }

    $cmbIpa.SelectedIndex = $index
})

# --- free / open-source statement ------------------------------------------
#
# Shown once on a fresh install (see $script:NoticeFile) and again from the
# footer link at any time. Measured behaviour, not a preference: a modeless
# window shown from this form's Shown handler -- while the main form is itself
# inside ShowDialog -- is created enabled but never receives input, so it could
# be neither clicked nor dismissed. A nested ShowDialog works, so the notice is
# always modal. The dialog title deliberately avoids "Zombie Farm": the
# automation in _analysis\ finds the manager window by that phrase.

function Test-NoticeSuppressed {
    return ($env:ZFR_MANAGER_NO_NOTICE -eq '1')
}

# Only decides the wording ("欢迎使用" vs plain), not whether the dialog appears:
# it appears on every launch now. See the note beside $script:NoticeVersion.
function Test-NoticeFirstRun {
    return -not (Test-Path -LiteralPath $script:NoticeFile -PathType Leaf)
}

function Set-NoticeSeen {
    try {
        [System.IO.File]::WriteAllText(
            $script:NoticeFile, $script:NoticeVersion, [System.Text.Encoding]::ASCII)
    } catch { }
}

# A short fingerprint the player can compare against the published Release
# notes, so "is this file the one they shipped" has an answer that does not
# depend on trusting whoever handed them the folder.
#
function Get-ManagerFingerprint {
    try {
        return (Get-Sha256Hex $script:ManagerPath).Substring(0, 16)
    } catch {
        return '未知'
    }
}

# --- official-file fingerprints ---------------------------------------------
#
# One row per file that can be pinned to a known-good hash. The expected values
# come from $script:PinnedExeSha256 / $script:PinnedIpaSha256 near the top and
# are refreshed with every release.
#
# Cost: about 90 MB of reads (exe 29 MB + IPA 59 MB), once at startup and once
# per 重新校验. That is a fraction of a second on any disk from the last decade.

function Update-IntegrityDisplay {
    if (-not $script:VerifyRowControls -or $script:VerifyRowControls.Count -eq 0) { return }

    $rows = @($script:IntegrityRows)
    for ($i = 0; $i -lt $script:VerifyRowControls.Count; $i++) {
        $ui = $script:VerifyRowControls[$i]
        if ($i -ge $rows.Count -or $null -eq $rows[$i]) {
            $ui.Name.Text = ''
            $ui.Expect.Text = ''
            $ui.Actual.Text = ''
            $ui.Verdict.Text = ''
            continue
        }

        $row = $rows[$i]
        $ui.Name.Text = $row.Name
        $ui.Expect.Text = if ($row.Expected) { $row.Expected.Substring(0, 16) + '…' } else { '（无固定值）' }
        $ui.Actual.Text = if ($row.Actual) { $row.Actual.Substring(0, 16) + '…' } else { '—' }
        switch ($row.State) {
            'ok'      { $ui.Verdict.Text = '✓ 与官方一致';   $ui.Verdict.ForeColor = $script:Forest }
            'bad'     { $ui.Verdict.Text = '✗ 与官方不一致'; $ui.Verdict.ForeColor = $script:Red }
            'missing' { $ui.Verdict.Text = '✗ 文件不存在';   $ui.Verdict.ForeColor = $script:Red }
            'unreadable' { $ui.Verdict.Text = '无法读取文件'; $ui.Verdict.ForeColor = $script:Amber }
            default   { $ui.Verdict.Text = '仅显示 · 与 Release 说明比对'; $ui.Verdict.ForeColor = $script:Grey }
        }
    }

    $script:LblVerifySelection.Text = if (-not $script:CurrentIpa.Path) {
        '当前选择：没有可用的游戏包'
    } elseif (Test-BundledIpa $script:CurrentIpa.Path) {
        '当前选择：内置游戏 IPA'
    } else {
        ('当前选择：{0}　（自选游戏包）' -f (Split-Path -Leaf $script:CurrentIpa.Path))
    }
}

# Recompute everything and refresh the page. Returns the headline, so callers do
# not have to look inside $script:IntegrityRows.
function Invoke-IntegrityCheck {
    $script:IntegrityRows = @(Get-IntegrityReport)
    Update-IntegrityDisplay
    return (Get-IntegrityHeadline $script:IntegrityRows)
}

function Open-ProjectUrl {
    try {
        [System.Diagnostics.Process]::Start($script:ProjectUrl) | Out-Null
    } catch {
        [void][System.Windows.Forms.MessageBox]::Show(
            ("无法自动打开浏览器。请手动访问：`n`n{0}" -f $script:ProjectUrl),
            '免费开源声明', 'OK', 'Information')
    }
}

function Show-ProjectNotice {
    param(
        [switch]$FirstRun,
        # The headline from Invoke-IntegrityCheck. Callers that already have it
        # pass it in; the footer link does not, so it is computed on demand.
        $Integrity
    )

    if (-not $Integrity) {
        if (@($script:IntegrityRows).Count -gt 0) {
            $Integrity = Get-IntegrityHeadline $script:IntegrityRows
        } else {
            $Integrity = Invoke-IntegrityCheck
        }
    }

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = if ($FirstRun) { '欢迎使用 · 免费开源声明' } else { '免费开源声明' }
    $dlg.Font = $font
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.ShowInTaskbar = $false
    $dlg.StartPosition = 'CenterParent'
    $dlg.ClientSize = New-Object System.Drawing.Size(560, 400)
    $dlg.BackColor = $script:Paper
    $dlg.ForeColor = $script:Ink

    $heading = New-Object System.Windows.Forms.Label
    $heading.Text = '本软件完全免费、开源'
    $heading.Font = $fontBold
    $heading.ForeColor = $script:Forest
    $heading.Location = New-Object System.Drawing.Point(22, 16)
    $heading.AutoSize = $true
    $dlg.Controls.Add($heading)

    $body = New-Object System.Windows.Forms.Label
    $body.Text = @(
        '任何人都可以从下面的官方地址免费下载，不需要付款，也没有付费版。'
        ''
        ('官方地址：{0}' -f $script:ProjectUrl)
        ('交流群：QQ {0}（免费使用；遇到问题、想反馈都可以来群里说）' -f $script:QqGroup)
        ''
        '如果你是花钱买到这个软件包的：你买到的只是一份免费的公开文件，'
        '请尽快向卖家申请退款，并向平台举报那条商品。本项目不通过任何中间渠道销售，'
        '也不对转卖渠道提供任何支持。'
        ''
        '· 基于 touchHLE 模拟器制作，非官方同人作品；模拟器部分遵循 MPL-2.0 许可。'
        '· 游戏素材版权归原开发商所有，本项目仅供个人学习与怀旧使用。'
        '· 发行包不含任何玩家存档，首次进入游戏会新建进度。'
    ) -join "`r`n"
    $body.Location = New-Object System.Drawing.Point(22, 48)
    $body.Size = New-Object System.Drawing.Size(516, 262)
    $body.ForeColor = $script:Ink
    $dlg.Controls.Add($body)

    $fingerprint = New-Object System.Windows.Forms.Label
    $fingerprint.Text = ('管理器版本标识：{0}（与 Release 说明中的哈希比对）' -f (Get-ManagerFingerprint))
    $fingerprint.Font = $fontSmall
    $fingerprint.ForeColor = $script:Grey
    $fingerprint.Location = New-Object System.Drawing.Point(24, 314)
    $fingerprint.Size = New-Object System.Drawing.Size(516, 20)
    $dlg.Controls.Add($fingerprint)

    # The same verdict the 文件校验 page gives, in one line. It is here because
    # this dialog is the one screen every launch cannot skip: if the program has
    # been tampered with, the player finds out before playing, not after.
    $verifyLine = New-Object System.Windows.Forms.Label
    $verifyLine.Text = $Integrity.Text
    $verifyLine.Font = $fontSmall
    $verifyLine.Location = New-Object System.Drawing.Point(24, 334)
    $verifyLine.Size = New-Object System.Drawing.Size(516, 20)
    $verifyLine.ForeColor = switch ($Integrity.Level) {
        'bad'   { $script:Red }
        'warn'  { $script:Amber }
        default { $script:Forest }
    }
    $dlg.Controls.Add($verifyLine)

    $btnOpen = New-Object System.Windows.Forms.Button
    $btnOpen.Text = '打开项目主页'
    $btnOpen.Size = New-Object System.Drawing.Size(122, 34)
    $btnOpen.Location = New-Object System.Drawing.Point(22, 358)
    $btnOpen.FlatStyle = 'Flat'
    $btnOpen.BackColor = $script:Forest
    $btnOpen.ForeColor = [System.Drawing.Color]::White
    $btnOpen.FlatAppearance.BorderSize = 0
    $btnOpen.Add_Click({ Open-ProjectUrl })
    $dlg.Controls.Add($btnOpen)

    $btnCopy = New-Object System.Windows.Forms.Button
    $btnCopy.Text = '复制链接'
    $btnCopy.Size = New-Object System.Drawing.Size(96, 34)
    $btnCopy.Location = New-Object System.Drawing.Point(156, 358)
    $btnCopy.FlatStyle = 'Flat'
    $btnCopy.BackColor = $script:SoftGreen
    # Secondary buttons follow the main window's rule: the lighter sage reads on
    # dark, the darker forest reads on light. Using forest in both themes made
    # this dialog's buttons look disabled in night mode.
    $btnCopy.ForeColor = if ($script:NightMode) { $script:Sage } else { $script:Forest }
    $btnCopy.FlatAppearance.BorderColor = $script:Line
    $btnCopy.Add_Click({
        try {
            [System.Windows.Forms.Clipboard]::SetText($script:ProjectUrl)
            $btnCopy.Text = '已复制'
        } catch {
            [void][System.Windows.Forms.MessageBox]::Show(
                ($script:ProjectUrl), '请手动复制这个地址', 'OK', 'Information')
        }
    })
    $dlg.Controls.Add($btnCopy)

    $btnClose = New-Object System.Windows.Forms.Button
    $btnClose.Text = if ($FirstRun) { '我知道了，开始使用' } else { '关闭' }
    $btnClose.Size = New-Object System.Drawing.Size(158, 34)
    $btnClose.Location = New-Object System.Drawing.Point(380, 358)
    $btnClose.FlatStyle = 'Flat'
    $btnClose.BackColor = $script:SoftGreen
    $btnClose.ForeColor = if ($script:NightMode) { $script:Sage } else { $script:Forest }
    $btnClose.FlatAppearance.BorderColor = $script:Line
    $btnClose.Add_Click({ $dlg.Close() })
    $dlg.Controls.Add($btnClose)
    $dlg.AcceptButton = $btnClose
    $dlg.CancelButton = $btnClose

    $dlg.Add_FormClosed({
        # Written on every close now: the dialog itself is not gated any more,
        # the marker only tells the next launch that this is no longer install #1.
        Set-NoticeSeen
        $dlg.Dispose()
    })

    # The main window gets a dark title bar; the dialog has to match it, or a
    # night-mode user sees one bright strip in an otherwise dark UI.
    $null = $dlg.Handle
    if ($script:NightMode) {
        [WindowChrome]::Apply(
            $dlg.Handle, $true,
            [int][WindowChrome]::PackColor($script:Paper),
            [int][WindowChrome]::PackColor($script:Ink),
            [int][WindowChrome]::PackColor($script:Line))
    }

    # Modal: see the note above -- a modeless window here cannot be dismissed.
    [void]$dlg.ShowDialog($form)
}

# --- startup / shutdown ----------------------------------------------------

$form.Add_Shown({
    $script:UiReady = $false       # suppress saves while the lists initialise
    Initialize-IpaList
    Load-SettingsIntoUi
    Refresh-Currency
    Update-SaveTab
    $script:UiReady = $true
    Update-Status '就绪。改动会立即保存。' 'info'
    Set-ManagerPalette -Night $script:NightMode
    # Hash the shipped files once, so the dialog and the 文件校验 page can both
    # report on it without hashing twice.
    $headline = Invoke-IntegrityCheck
    if (-not (Test-NoticeSuppressed)) {
        # -FirstRun:( ... ) and not -FirstRun ( ... ): a switch does not take a
        # space-separated value, it silently becomes true and the expression is
        # dropped. That made every launch show the "welcome" title.
        Show-ProjectNotice -FirstRun:(Test-NoticeFirstRun) -Integrity $headline
    }
})

$form.Add_FormClosing({
    if (Test-GameRunning) {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            '游戏还在运行。关闭这个管理窗口不会关闭游戏，确定关闭吗？',
            '确认', 'YesNo', 'Question')
        if ($answer -ne 'Yes') { $_.Cancel = $true }
    }
})

function Set-ManagerPalette {
    param([bool]$Night)

    if ($Night) {
        $script:Ink = [System.Drawing.Color]::FromArgb(232, 237, 234)
        $script:Grey = [System.Drawing.Color]::FromArgb(165, 179, 173)
        $script:Red = [System.Drawing.Color]::FromArgb(224, 126, 116)
        $script:Forest = [System.Drawing.Color]::FromArgb(76, 139, 111)
        $script:Sage = [System.Drawing.Color]::FromArgb(126, 177, 146)
        $script:Amber = [System.Drawing.Color]::FromArgb(214, 168, 99)
        $script:Paper = [System.Drawing.Color]::FromArgb(29, 35, 38)
        $script:Surface = [System.Drawing.Color]::FromArgb(38, 46, 48)
        $script:SoftGreen = [System.Drawing.Color]::FromArgb(48, 65, 56)
        $script:SaveSelection = [System.Drawing.Color]::FromArgb(50, 83, 69)
        $script:SaveSelectionAccent = $script:Sage
        $script:Line = [System.Drawing.Color]::FromArgb(49, 59, 56)
        $hover = [System.Drawing.Color]::FromArgb(88, 151, 122)
        $pressed = [System.Drawing.Color]::FromArgb(61, 119, 96)
    } else {
        $script:Ink = [System.Drawing.Color]::FromArgb(38, 52, 58)
        $script:Grey = [System.Drawing.Color]::FromArgb(105, 122, 120)
        $script:Red = [System.Drawing.Color]::FromArgb(184, 78, 74)
        $script:Forest = [System.Drawing.Color]::FromArgb(45, 101, 87)
        $script:Sage = [System.Drawing.Color]::FromArgb(111, 148, 127)
        $script:Amber = [System.Drawing.Color]::FromArgb(214, 160, 82)
        $script:Paper = [System.Drawing.Color]::FromArgb(243, 246, 244)
        $script:Surface = [System.Drawing.Color]::White
        $script:SoftGreen = [System.Drawing.Color]::FromArgb(228, 236, 231)
        $script:SaveSelection = [System.Drawing.Color]::FromArgb(208, 231, 219)
        $script:SaveSelectionAccent = $script:Forest
        $script:Line = [System.Drawing.Color]::FromArgb(220, 228, 223)
        $hover = [System.Drawing.Color]::FromArgb(36, 83, 71)
        $pressed = [System.Drawing.Color]::FromArgb(39, 89, 75)
    }

    function Set-ControlColors($control) {
        if ($control -is [System.Windows.Forms.Label]) { $control.ForeColor = $script:Ink }
        elseif ($control -is [PaletteGroupBox]) {
            $control.BorderColor = $script:Line
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        elseif ($control -is [System.Windows.Forms.TabPage]) {
            $control.UseVisualStyleBackColor = $false
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        elseif ($control -is [System.Windows.Forms.TabControl]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        elseif ($control -is [PaletteComboBox]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Surface
            $control.ArrowColor = $script:Surface
            $control.ArrowBorderColor = $script:Line
            $control.ArrowGlyphColor = $script:Grey
        }
        elseif ($control -is [System.Windows.Forms.TextBox]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Surface
            $control.BorderStyle = [System.Windows.Forms.BorderStyle]::None
        }
        elseif ($control -is [System.Windows.Forms.NumericUpDown] -or
                $control -is [System.Windows.Forms.ListView]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Surface
        }
        elseif ($control -is [System.Windows.Forms.CheckBox]) {
            $control.ForeColor = $script:Ink; $control.BackColor = $script:Paper
        }
        foreach ($child in $control.Controls) { Set-ControlColors $child }
    }

    $form.BackColor = $script:Paper; $form.ForeColor = $script:Ink
    foreach ($control in $form.Controls) { Set-ControlColors $control }
    $tabs.StripColor = $script:Paper
    $tabs.BorderColor = $script:Line
    $tabs.TabColor = $script:Surface
    $tabs.SelectedTabColor = $script:Forest
    $tabs.TabTextColor = if ($Night) { $script:Grey } else { $script:Ink }
    $tabs.SelectedTabTextColor = [System.Drawing.Color]::White
    $title.ForeColor = $script:Ink
    $subtitle.ForeColor = $script:Grey
    $btnTheme.Tag = if ($Night) { [char]0xE708 } else { [char]0xE706 }
    $btnTheme.BackColor = $script:Surface
    $btnTheme.ForeColor = $script:Forest
    $btnTheme.FlatAppearance.BorderColor = $script:Line
    $themeTip.SetToolTip($btnTheme, $(if ($Night) { '切换到日间模式' } else { '切换到夜间模式' }))
    $btnTheme.Invalidate()
    $headerRule.BackColor = $script:Amber
    $lblIpaInfo.ForeColor = $script:Grey
    $lblSimulatedTime.ForeColor = $script:Ink
    $lblCurrencyState.ForeColor = $script:Grey
    $lblSaveInfo.ForeColor = $script:Grey
    $lblSaveHint.ForeColor = $script:Grey
    $lblVerifyNote.ForeColor = $script:Grey
    $lblVerifyState.ForeColor = $script:Grey
    $lblChannelUrl.ForeColor = $script:Grey
    $lblChannelQq.ForeColor = $script:Grey
    if ($script:LblVerifySelection) { $script:LblVerifySelection.ForeColor = $script:Grey }
    foreach ($lbl in $script:VerifyHeaderLabels) { $lbl.ForeColor = $script:Grey }
    $status.ForeColor = $script:Grey
    $noticeLink.LinkColor = $script:Sage
    $noticeLink.ActiveLinkColor = $script:Amber
    $noticeLink.VisitedLinkColor = $script:Sage
    $noticeLink.ForeColor = $script:Grey
    $noticeLink.BackColor = $script:Paper

    # The 文件校验 verdicts carry their own colours (green / red), which the
    # generic walk above just overwrote with ink. Re-apply them now that the
    # palette is current.
    Update-IntegrityDisplay

    foreach ($button in @(
        $btnIpaBrowse, $btnStartSkip, $btnResetTime, $btnApplyCurrency, $btnBackup, $btnRestore,
        $btnRefresh, $btnSelectAll, $btnSelectNone, $btnSelectInvert, $btnDelete
    )) {
        $button.BackColor = $script:SoftGreen
        $button.ForeColor = if ($Night) { $script:Sage } else { $script:Forest }
        $button.FlatStyle = 'Flat'
        $button.FlatAppearance.BorderColor = $script:Line
    }
    $btnStart.BackColor = $script:Forest
    $btnStart.ForeColor = [System.Drawing.Color]::White
    $btnStart.FlatAppearance.MouseOverBackColor = $hover
    $btnStart.FlatAppearance.MouseDownBackColor = $pressed
    if ($script:LblWindowSize) { $script:LblWindowSize.ForeColor = $script:Sage }
    if ($form.IsHandleCreated) {
        $captionColor = if ($Night) { [WindowChrome]::PackColor($script:Paper) } else { -1 }
        $captionTextColor = if ($Night) { [WindowChrome]::PackColor($script:Ink) } else { -1 }
        $captionBorderColor = if ($Night) { [WindowChrome]::PackColor($script:Line) } else { -1 }
        [WindowChrome]::Apply(
            $form.Handle, $Night, [int]$captionColor,
            [int]$captionTextColor, [int]$captionBorderColor)
    }
    $tabs.Invalidate()
    $listSaves.Invalidate()
}

$tabs.Add_DrawItem({
    param($sender, $eventArgs)
    $selected = $eventArgs.Index -eq $sender.SelectedIndex
    $background = if ($selected) { $script:Forest } else { $script:Surface }
    $foreground = if ($selected) { [System.Drawing.Color]::White } elseif ($script:NightMode) { $script:Grey } else { $script:Ink }
    $fill = New-Object System.Drawing.SolidBrush($background)
    $textBrush = New-Object System.Drawing.SolidBrush($foreground)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    try {
        $eventArgs.Graphics.FillRectangle($fill, $eventArgs.Bounds)
        $bounds = $eventArgs.Bounds
        $text = $sender.TabPages[$eventArgs.Index].Text.Trim()
        $size = $eventArgs.Graphics.MeasureString($text, $sender.Font)
        $x = $bounds.Left + (($bounds.Width - $size.Width) / 2)
        $y = $bounds.Top + (($bounds.Height - $size.Height) / 2)
        $eventArgs.Graphics.DrawString($text, $sender.Font, $textBrush, [single]$x, [single]$y)
    } finally {
        $fill.Dispose(); $textBrush.Dispose(); $format.Dispose()
    }
})

Set-ManagerPalette -Night $script:NightMode
$btnTheme.Add_Click({
    $script:NightMode = -not $script:NightMode
    [System.IO.File]::WriteAllText(
        $script:NightModeFile,
        $(if ($script:NightMode) { '1' } else { '0' }),
        [System.Text.Encoding]::ASCII)
    Set-ManagerPalette -Night $script:NightMode
})

# --- size the window to its content ----------------------------------------
#
# Done here, after every control exists, so the numbers are measured rather than
# guessed. Two things this fixes, both of which happened:
#
#   * the game tab grew when the IPA picker was added, leaving 金币与脑子 flush
#     against the tab's bottom edge
#   * the window had a large blank area below the tabs when a tab was shortened
#
# The tab's usable height is its total height minus the row of tab headers, which
# is what the "+tabHeaderAllowance" accounts for. The window follows the selected
# page so compact pages do not inherit a blank area from the save list.

$tabHeaderAllowance = 26
$bottomMargin = 18

$gameNeeded = [Math]::Max(
    ($grpCurrency.Top + $grpCurrency.Height),
    ($btnStartSkip.Top + $btnStartSkip.Height))
$settingsNeeded = $grpSettings.Top + $grpSettings.Height
$saveNeeded = $lblSaveHint.Top + $lblSaveHint.Height
# The verify page ends at the 官方渠道 box. Nothing on it grows, so it gets no
# slack -- it is simply shorter than the save tab and the window shrinks to fit.
$verifyNeeded = $grpChannels.Top + $grpChannels.Height

$script:GameContentHeight = $gameNeeded + $bottomMargin
$script:SettingsContentHeight = $settingsNeeded + $bottomMargin
$script:SaveContentHeight = $saveNeeded + $bottomMargin
$script:VerifyContentHeight = $verifyNeeded + $bottomMargin
$contentHeight = [Math]::Max(
    [Math]::Max($script:GameContentHeight, $script:SettingsContentHeight),
    [Math]::Max($script:SaveContentHeight, $script:VerifyContentHeight))

# Give any leftover height to the save list, so the shorter tab fills the space
# instead of showing a gap. The list is the only element there that benefits from
# being taller.
$slack = $contentHeight - $script:SaveContentHeight
if ($slack -gt 0) {
    $listSaves.Height = $listSaves.Height + $slack
    $btnSelectAll.Top = $btnSelectAll.Top + $slack
    $btnSelectNone.Top = $btnSelectNone.Top + $slack
    $btnSelectInvert.Top = $btnSelectInvert.Top + $slack
    $lblSaveHint.Top = $lblSaveHint.Top + $slack
    $script:SaveContentHeight += $slack
}

function Update-WindowForSelectedTab {
    if ($tabs.SelectedIndex -eq 2) { $pageHeight = $script:SaveContentHeight }
    elseif ($tabs.SelectedIndex -eq 1) { $pageHeight = $script:SettingsContentHeight }
    elseif ($tabs.SelectedIndex -eq 3) { $pageHeight = $script:VerifyContentHeight }
    else { $pageHeight = $script:GameContentHeight }
    $tabs.Height = $pageHeight + $tabHeaderAllowance
    $status.Top = $tabs.Top + $tabs.Height + 6
    $noticeLink.Top = $status.Top + $status.Height
    $form.ClientSize = [System.Drawing.Size]::new(
        $form.ClientSize.Width,
        [int]($noticeLink.Top + $noticeLink.Height + 8))
}

$tabs.Add_SelectedIndexChanged({ Update-WindowForSelectedTab })
Update-WindowForSelectedTab

[void]$form.ShowDialog()
$clockTimer.Dispose()
$form.Dispose()
