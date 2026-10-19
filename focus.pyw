"""High-DPI, standalone focus widget drawn in the AI limit card's design language."""
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from datetime import date
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QPoint, QLockFile
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QLinearGradient, QFont, QPen, QImage,
    QFontDatabase, QCursor, QIcon, QPixmap)
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QSystemTrayIcon, QFileDialog
import chimes
from focus_engine import FocusTimer, RANGES, period, streak

ROOT = Path(__file__).resolve().parent
UI_STATE = ROOT/'state'/'ui.json'
USAGE_WINDOW = ROOT.parent/'usage-widget'/'state'/'window.json'
# Same palette and canvas as usage-widget/widget.pyw so every card reads as one set.
BLUE = QColor('#009cff')
TEXT = QColor('#f5f5f5')
MUTED = QColor('#999999')
CANVAS_W = 554
TABS = [('focus','Focus',96),('short','Short break',132),('long','Long break',128)]
MENU_STYLE = ('QMenu { background:#252525; color:#f5f5f5; padding:6px; } QMenu::item { padding:7px 20px; }'
              ' QMenu::item:selected { background:#007acc; }')
LEFT = Qt.AlignmentFlag.AlignLeft
RIGHT = Qt.AlignmentFlag.AlignRight
CENTER = Qt.AlignmentFlag.AlignHCenter

def read_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def hm(seconds):
    m = int(seconds//60)
    return f'{m//60}h {m%60:02d}m'

def goal_label(minutes):
    return f'{minutes//60}h' + (f' {minutes%60:02d}m' if minutes % 60 else '')

MODE_NAMES = {'focus':'Focus','short':'Short break','long':'Long break'}
# (title, body) shown when the timer switches INTO this mode; {n} = its length in minutes.
MESSAGES = {'short':('Focus complete','Time for a {n}-minute short break.'),
            'long':('Focus complete · long break','Round done. Take a {n}-minute long break.'),
            'focus':('Break over','Ready for {n} minutes of focus.')}

def plural(n, word):
    return f'{n} {word}{"" if n == 1 else "s"}'

def draw_text(p, rect, value, size=19, color=TEXT, bold=False, align=LEFT):
    font = QFont('Segoe UI'); font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    p.setFont(font); p.setPen(color)
    p.drawText(QRectF(*rect), Qt.AlignmentFlag.AlignVCenter | align, value)

def draw_card(p, width, height):
    path = QPainterPath(); path.addRoundedRect(QRectF(.6,.6,width-1.2,height-1.2),52,52)
    gradient = QLinearGradient(0,0,0,height*.68)
    gradient.setColorAt(0,QColor('#313131')); gradient.setColorAt(1,QColor('#1d1d1d'))
    p.fillPath(path,gradient)
    p.setPen(QPen(QColor(110,110,110,100),1)); p.drawPath(path)

def draw_icon(p, x, y):
    # Stopwatch: ring + crown, sized like the usage card's provider icons (30 x 25).
    p.save(); p.translate(x,y)
    p.setPen(QPen(BLUE,3)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(5,4,21,21))
    p.setPen(QPen(BLUE,3,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(12,.5),QPointF(19,.5))
    p.setPen(QPen(TEXT,2.2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(15.5,14.5),QPointF(15.5,9))
    p.drawLine(QPointF(15.5,14.5),QPointF(19.5,16.5))
    p.restore()

def draw_pill(p, rect, label, active=False, hover=False, size=15):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#17445b') if active else QColor('#3a3a3a' if hover else '#2c2c2c'))
    p.drawRoundedRect(rect,rect.height()/2,rect.height()/2)
    draw_text(p,(rect.x(),rect.y()+4,rect.width(),rect.height()-8),label,size,
              QColor('#68c7ff') if active else QColor('#c8c8c8'),active,CENTER)

def draw_circle(p, rect, hover=False, primary=False, enabled=True):
    p.setPen(Qt.PenStyle.NoPen)
    if primary: color = QColor('#25acff') if hover else BLUE
    else: color = QColor('#484848') if hover and enabled else QColor('#383838' if enabled else '#2a2a2a')
    p.setBrush(color); p.drawEllipse(rect)

def glyph_pen(enabled=True, width=2.2):
    return QPen(TEXT if enabled else QColor('#5c5c5c'),width,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin)

def draw_glyph(p, rect, kind, enabled=True):
    c = rect.center(); x, y = c.x(), c.y()
    p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(glyph_pen(enabled))
    if kind == 'close':
        p.drawLine(QPointF(x-6,y-6),QPointF(x+6,y+6)); p.drawLine(QPointF(x+6,y-6),QPointF(x-6,y+6))
    elif kind == 'minus':
        p.drawLine(QPointF(x-7,y),QPointF(x+7,y))
    elif kind == 'plus':
        p.drawLine(QPointF(x-7,y),QPointF(x+7,y)); p.drawLine(QPointF(x,y-7),QPointF(x,y+7))
    elif kind in ('prev','next'):
        d = -1 if kind == 'prev' else 1
        p.drawLine(QPointF(x-3*d,y-7),QPointF(x+4*d,y)); p.drawLine(QPointF(x+4*d,y),QPointF(x-3*d,y+7))

def clamp_to_screen(widget):
    center = widget.frameGeometry().center()
    screen = next((s for s in QApplication.screens() if s.availableGeometry().contains(center)),QApplication.primaryScreen())
    a = screen.availableGeometry()
    if a.bottom() == screen.geometry().bottom():
        a.adjust(0, 0, 0, -48)  # Keep clear of the auto-hidden taskbar.
    widget.move(max(a.left(),min(widget.x(),a.right()-widget.width()+1)),
                max(a.top(),min(widget.y(),a.bottom()-widget.height()+1)))


class FocusWidget(QWidget):
    H = 324

    def __init__(self, preview=False):
        super().__init__()
        self.preview = preview
        self.engine = FocusTimer(ROOT/'state'/'focus.json')
        self.ui = read_json(UI_STATE)
        self.options = self.ui  # desktop_layer reads options['topmost']
        scale = self.ui.get('scale', read_json(USAGE_WINDOW).get('scale', .65))
        self.scale = scale if isinstance(scale, (int, float)) and .4 <= scale <= 1.5 else .65
        self.panels = {}
        self.offset = None
        self.pressed = None
        self.hover = None
        self.setWindowTitle('Focus Timer')
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        if self.ui.get('topmost'):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(round(CANVAS_W*self.scale), round(self.H*self.scale))
        self.buttons = {'play': QRectF(461,138,64,64), 'reset': QRectF(397,144,52,52)}
        x = 29
        for mode, _, width in TABS:
            self.buttons[mode] = QRectF(x,80,width,34); x += width+8
        area = QApplication.primaryScreen().availableGeometry()
        pos = self.engine.position
        if isinstance(pos,list) and len(pos)==2 and all(isinstance(n,int) for n in pos): self.move(*pos)
        else: self.move(area.right()-self.width()-30,area.bottom()-self.height()-30)
        self.clamp()
        self.last_save = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.setInterval(250)
        self.layer = None
        self.tray = None
        self.sounds = {}
        self.start_on_click = False
        self.tray_text = ''
        self.goal_done = self.goal_reached()
        if not preview:
            from desktop_layer import DesktopLayer
            self.layer = DesktopLayer(self)
            self.setup_alerts()
            self.timer.start()
        for screen in QApplication.screens(): screen.availableGeometryChanged.connect(self.clamp)
        QApplication.instance().screenRemoved.connect(self.clamp)

    def clamp(self,*args):
        clamp_to_screen(self)

    def save(self):
        if self.preview: return
        self.engine.position=[self.x(),self.y()]
        try: self.engine.save()
        except OSError: self.engine.notice='Could not save · check disk access'

    def save_ui(self):
        if self.preview: return
        self.ui.update(scale=self.scale, topmost=bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        try:
            tmp = UI_STATE.with_suffix('.tmp'); tmp.write_text(json.dumps(self.ui), encoding='utf-8'); os.replace(tmp, UI_STATE)
        except OSError: pass

    def tick(self):
        completed=self.engine.tick()
        if completed: self.alert(self.engine.mode)
        self.check_goal()
        self.update_tray()
        if completed or time.monotonic()-self.last_save >=5:
            self.save()
            self.last_save=time.monotonic()
        self.update()
        if 'history' in self.panels: self.panels['history'].update()
        if self.layer: self.layer.maintain()

    # --- sound, tray and notifications ---
    def setup_alerts(self):
        # winsound, not QSoundEffect: Qt reported "playing" here while nothing was audible.
        try: self.sounds = {name: path.read_bytes() for name, path in chimes.ensure(ROOT/'sounds').items()}
        except OSError: self.sounds = {}
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.tray_icon(False), self)
            self.tray_menu = QMenu(); self.tray_menu.setStyleSheet(MENU_STYLE)
            self.tray_menu.aboutToShow.connect(lambda: self.fill_menu(self.tray_menu))
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self.tray_activated)
            self.tray.messageClicked.connect(self.message_clicked)
            self.tray.show(); self.update_tray()

    @staticmethod
    def tray_icon(running):
        pix = QPixmap(64,64); pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(BLUE if running else QColor('#3a3a3a')); p.drawEllipse(QRectF(2,2,60,60))
        p.setPen(QPen(TEXT,5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(32,33),QPointF(32,17)); p.drawLine(QPointF(32,33),QPointF(43,39))
        p.end(); return QIcon(pix)

    def update_tray(self):
        if not self.tray: return
        secs = math.ceil(self.engine.remaining)
        text = f'{MODE_NAMES[self.engine.mode]} · {secs//60:02d}:{secs%60:02d}' + ('' if self.engine.running else ' · paused')
        if text != self.tray_text:
            if self.tray_text.endswith('paused') != text.endswith('paused') or not self.tray_text:
                self.tray.setIcon(self.tray_icon(self.engine.running))
            self.tray_text = text; self.tray.setToolTip('Focus Timer\n'+text)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger: self.toggle()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick: self.history()

    def play(self, name, volume=None):
        data = self.sounds.get(name)
        volume = self.engine.settings['volume'] if volume is None else volume
        if data and volume:
            threading.Thread(target=chimes.play, args=(data, volume/100), daemon=True).start()

    def notify(self, title, body):
        if self.tray and self.engine.settings['notify'] and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, body, self.tray_icon(True), 10000)

    def alert(self, mode):
        """The timer just switched into `mode`: chime for that phase and send a notification."""
        if self.engine.settings['sound']: self.play(mode)
        title, body = MESSAGES[mode]
        body = body.format(n=self.engine.settings[mode])
        self.start_on_click = not self.engine.running
        self.notify(title, body + (' Started automatically.' if self.engine.running else ' Click here to start.'))

    def message_clicked(self):
        if self.start_on_click and not self.engine.running: self.toggle()
        self.start_on_click = False

    def goal_reached(self):
        goal = self.engine.settings['goal']
        return bool(goal) and self.engine.days.get(date.today().isoformat(),{}).get('seconds',0) >= goal*60

    def check_goal(self):
        reached = self.goal_reached()
        if reached and not self.goal_done:
            if self.engine.settings['sound']: self.play('long')
            self.start_on_click = False
            self.notify('Daily goal reached', f'{goal_label(self.engine.settings["goal"])} of focus today. Nice work.')
        self.goal_done = reached

    def export_csv(self):
        default = str(Path.home()/'Documents'/f'focus-history-{date.today()}.csv')
        path, _ = QFileDialog.getSaveFileName(self, 'Export focus history', default, 'CSV (*.csv)')
        if not path: return
        rows = ['date,focus_minutes,sessions'] + [f'{d},{v.get("seconds",0)/60:.1f},{v.get("sessions",0)}'
                                                  for d,v in sorted(self.engine.days.items())]
        try: Path(path).write_text('\n'.join(rows)+'\n', encoding='utf-8'); self.engine.notice = 'History exported'
        except OSError: self.engine.notice = 'Export failed · check the folder'
        self.update()

    def toggle(self):
        self.engine.tick(); self.engine.start_pause(); self.save(); self.update(); self.update_tray()

    def skip(self):
        self.engine.tick(); self.engine.skip(); self.save(); self.update(); self.update_tray()

    def extend(self):
        self.engine.tick(); self.engine.extend(); self.save(); self.update(); self.update_tray()

    def reset(self):
        self.engine.tick(); self.engine.reset(); self.save(); self.update()

    def select_mode(self,mode):
        if mode==self.engine.mode: return
        self.engine.tick(); self.engine.switch(mode); self.save(); self.update()

    def paintEvent(self,event):
        e=self.engine
        p=QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.scale(self.width()/CANVAS_W,self.height()/self.H)
        draw_card(p,CANVAS_W,self.H)
        draw_icon(p,29,34)
        draw_text(p,(70,30,300,37),'Focus Timer',25,bold=True)
        every=e.settings['every']
        draw_text(p,(29,35,496,25),f'Round {e.cycle % every + 1} of {every}',13,MUTED,align=RIGHT)
        for mode,label,_ in TABS: draw_pill(p,self.buttons[mode],label,mode==e.mode,self.hover==mode)
        secs=math.ceil(e.remaining)
        draw_text(p,(25,124,360,84),f'{secs//60:02d}:{secs%60:02d}',72,bold=True)
        draw_circle(p,self.buttons['reset'],self.hover=='reset')
        c=self.buttons['reset'].center(); p.setPen(glyph_pen())
        p.drawArc(QRectF(c.x()-9,c.y()-8,18,18),70*16,280*16)
        p.drawLine(QPointF(c.x()-1,c.y()-12),QPointF(c.x()+5,c.y()-8))
        p.drawLine(QPointF(c.x()+5,c.y()-8),QPointF(c.x()-1,c.y()-3))
        r=self.buttons['play']; draw_circle(p,r,self.hover=='play',primary=True); c=r.center()
        if e.running:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(TEXT)
            for dx in (-7,3): p.drawRoundedRect(QRectF(c.x()+dx,c.y()-10,5,20),1.5,1.5)
        else:
            tri=QPainterPath();tri.moveTo(c.x()-6,c.y()-11);tri.lineTo(c.x()+11,c.y());tri.lineTo(c.x()-6,c.y()+11);tri.closeSubpath()
            p.setBrush(TEXT); p.setPen(glyph_pen(width=2)); p.drawPath(tri)
        draw_text(p,(29,204,496,27),e.notice,15,MUTED)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#4b4b4d'))
        p.drawRoundedRect(QRectF(29,240,496,14),7,7)
        fraction=max(0,min(1,1-e.remaining/e.duration))
        if fraction:
            width=496*fraction;p.setBrush(BLUE)
            p.drawRoundedRect(QRectF(29,240,width,14),min(7,width/2),min(7,width/2))
        today=e.days.get(date.today().isoformat(),{})
        goal=e.settings['goal']; done=today.get('seconds',0)
        label=f'Today  {hm(done)}'+(f'  /  {goal_label(goal)}' if goal else '')
        draw_text(p,(29,266,330,31),label,19,QColor('#68c7ff') if goal and done>=goal*60 else TEXT)
        draw_text(p,(29,266,496,31),plural(today.get('sessions',0),'session'),19,MUTED,align=RIGHT)
        p.end()

    def open_panel(self,key,cls):
        panel=self.panels.get(key)
        if panel is None:
            panel=cls(self,key);self.panels[key]=panel
            panel.destroyed.connect(lambda *_,k=key:self.panels.pop(k,None))
        panel.show();panel.raise_();panel.activateWindow()

    def settings_dialog(self): self.open_panel('settings',SettingsPanel)
    def history(self): self.open_panel('history',HistoryPanel)

    def set_size(self,scale):
        self.scale=scale;self.setFixedSize(round(CANVAS_W*scale),round(self.H*scale))
        for panel in list(self.panels.values()): panel.close()
        self.clamp();self.save();self.save_ui();self.update()

    def toggle_top(self):
        on=not bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,on);self.show();self.save_ui()

    def hit(self,pos):
        point=QPointF(pos.x()*CANVAS_W/self.width(),pos.y()*self.H/self.height())
        return next((key for key,r in self.buttons.items() if r.contains(point)),None)

    def activate(self,key):
        if key=='play': self.toggle()
        elif key=='reset': self.reset()
        else: self.select_mode(key)

    def mousePressEvent(self,e):
        if e.button()!=Qt.MouseButton.LeftButton: return
        self.pressed=self.hit(e.position())
        if self.pressed is None and not self.ui.get('position_locked',False): self.offset=e.globalPosition().toPoint()-self.pos()
    def mouseMoveEvent(self,e):
        if self.offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint()-self.offset);return
        key=self.hit(e.position())
        if key!=self.hover:
            self.hover=key;self.update()
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor))
            self.setToolTip({'play':'Start / Pause','reset':'Reset timer'}.get(key,''))
    def leaveEvent(self,e):
        if self.hover: self.hover=None;self.update()
    def mouseReleaseEvent(self,e):
        if self.pressed and self.hit(e.position())==self.pressed: self.activate(self.pressed)
        elif self.offset is not None: self.clamp();self.save()
        self.pressed=None;self.offset=None
    def keyPressEvent(self,e):
        actions={Qt.Key.Key_Space:self.toggle,Qt.Key.Key_R:self.reset,Qt.Key.Key_S:self.skip,
                 Qt.Key.Key_Plus:self.extend,Qt.Key.Key_Equal:self.extend,Qt.Key.Key_H:self.history,
                 Qt.Key.Key_Comma:self.settings_dialog}
        if e.key() in actions: actions[e.key()]()
        else: super().keyPressEvent(e)
    def toggle_position_lock(self):
        self.ui['position_locked']=not self.ui.get('position_locked',False)
        self.offset=None
        self.save();self.save_ui()

    def contextMenuEvent(self,e):
        menu=QMenu(self);menu.setStyleSheet(MENU_STYLE);self.fill_menu(menu);menu.exec(e.globalPos())
    def fill_menu(self,menu):
        menu.clear()
        menu.addAction(('Pause' if self.engine.running else 'Start')+'\tSpace',self.toggle)
        menu.addAction('Reset\tR',self.reset)
        menu.addAction(('Skip to break' if self.engine.mode=='focus' else 'Skip to focus')+'\tS',self.skip)
        menu.addAction('Add 5 minutes\t+',self.extend)
        menu.addSeparator()
        menu.addAction('Settings…\t,',self.settings_dialog);menu.addAction('History…\tH',self.history)
        menu.addAction('Export history (CSV)…',self.export_csv)
        lock=menu.addAction('Lock position',self.toggle_position_lock);lock.setCheckable(True)
        lock.setChecked(self.ui.get('position_locked',False))
        sizes=menu.addMenu('Size')
        for name,scale in [('Small',.65),('Medium',.82),('Large',1.0),('Extra large',1.2)]:
            act=sizes.addAction(name,lambda s=scale:self.set_size(s));act.setCheckable(True);act.setChecked(abs(scale-self.scale)<.01)
        top=menu.addAction('Always on top',self.toggle_top);top.setCheckable(True)
        top.setChecked(bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        menu.addSeparator();menu.addAction('Quit',self.close)
    def closeEvent(self,e):
        for panel in list(self.panels.values()): panel.close()
        if self.tray: self.tray.hide()
        self.engine.tick();self.engine.running=False;self.save();e.accept()


class Panel(QWidget):
    """Draggable card window owned by the timer; remembers where it was dropped."""
    H = 400
    TITLE = ''

    def __init__(self, owner, key):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.owner, self.key = owner, key
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle(self.TITLE)
        self.setFixedSize(round(CANVAS_W*owner.scale), round(self.H*owner.scale))
        self.buttons = {'close': QRectF(489,32,36,36)}
        self.hover = self.pressed = self.offset = None
        self.place()

    def place(self):
        pos = self.owner.ui.get(self.key+'_pos')
        if isinstance(pos,list) and len(pos)==2 and all(isinstance(n,int) for n in pos):
            self.move(*pos)
        else:
            o = self.owner.frameGeometry()
            screen = QApplication.screenAt(o.center()) or QApplication.primaryScreen()
            a = screen.availableGeometry(); gap = 12
            x = o.left()-self.width()-gap if o.left()-self.width()-gap >= a.left() else o.right()+gap
            self.move(x, o.top())
        clamp_to_screen(self)

    def local(self, pos):
        return QPointF(pos.x()*CANVAS_W/self.width(), pos.y()*self.H/self.height())
    def hit(self, pos):
        point = self.local(pos)
        return next((key for key,r in self.buttons.items() if r.contains(point) and self.enabled(key)),None)
    def enabled(self, key): return True
    def activate(self, key):
        if key == 'close': self.close()

    def begin(self, title):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.scale(self.width()/CANVAS_W, self.height()/self.H)
        draw_card(p, CANVAS_W, self.H)
        draw_icon(p, 29, 34)
        draw_text(p, (70,30,330,37), title, 25, bold=True)
        draw_circle(p, self.buttons['close'], self.hover=='close'); draw_glyph(p, self.buttons['close'], 'close')
        return p

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton: return
        self.pressed = self.hit(e.position())
        if self.pressed is None: self.offset = e.globalPosition().toPoint()-self.pos()
    def mouseMoveEvent(self, e):
        if self.offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint()-self.offset); return
        key = self.hit(e.position())
        if key != self.hover:
            self.hover = key; self.update()
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor))
    def leaveEvent(self, e):
        if self.hover: self.hover = None; self.update()
    def mouseReleaseEvent(self, e):
        if self.pressed and self.hit(e.position()) == self.pressed: self.activate(self.pressed)
        elif self.offset is not None:
            clamp_to_screen(self)
            self.owner.ui[self.key+'_pos'] = [self.x(), self.y()]; self.owner.save_ui()
        self.pressed = self.offset = None
    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape: self.close()
        else: super().keyPressEvent(e)


class SettingsPanel(Panel):
    H = 716
    TITLE = 'Focus Settings'
    STEPPERS = [('focus','Focus','min'),('short','Short break','min'),('long','Long break','min'),
                ('every','Long break every','sessions'),('goal','Daily goal','per day'),('volume','Chime volume','%')]
    SWITCHES = [('auto_break','Start breaks automatically'),('auto_focus','Start focus automatically'),
                ('sound','Play a chime for each phase'),('notify','Show a notification')]
    STEP = {'every':1,'goal':30,'volume':10}

    def __init__(self, owner, key):
        super().__init__(owner, key)
        self.draft = dict(owner.engine.settings)
        for i,(k,_,_) in enumerate(self.STEPPERS):
            y = 88+i*52
            self.buttons[k+'-'] = QRectF(353,y+9,34,34); self.buttons[k+'+'] = QRectF(491,y+9,34,34)
        for i,(k,_) in enumerate(self.SWITCHES):
            self.buttons[k] = QRectF(29,424+i*48,496,40)
        self.buttons['cancel'] = QRectF(289,650,110,42); self.buttons['save'] = QRectF(411,650,114,42)

    @classmethod
    def step(cls, key, value, up):
        low, high = RANGES[key]
        if key in cls.STEP:
            size = cls.STEP[key]
            value = (value//size+1)*size if up else -(-value//size-1)*size
        elif up: value = value+1 if value < 5 else (value//5+1)*5
        else: value = value-1 if value <= 5 else ((value-1)//5)*5
        return max(low,min(high,value))

    def changed(self, key):
        if key == 'volume': self.owner.play('focus', self.draft['volume'])

    def enabled(self, key):
        if key.endswith('-') or key.endswith('+'):
            k = key[:-1]
            return self.step(k,self.draft[k],key.endswith('+')) != self.draft[k]
        return True

    def activate(self, key):
        if key.endswith('-') or key.endswith('+'):
            k = key[:-1]; self.draft[k] = self.step(k,self.draft[k],key.endswith('+')); self.changed(k)
        elif key in self.draft: self.draft[key] = not self.draft[key]
        elif key == 'save': self.apply(); self.close(); return
        else: super().activate(key); return
        self.update()

    def apply(self):
        engine = self.owner.engine
        engine.tick()
        timing = any(self.draft[k] != engine.settings[k] for k in ('focus','short','long','every'))
        engine.settings = dict(self.draft)
        if timing: engine.reset()  # a fresh, paused timer; recorded work is kept
        self.owner.save(); self.owner.update()

    def wheelEvent(self, e):
        point = self.local(e.position())
        for i,(k,_,_) in enumerate(self.STEPPERS):
            if 88+i*52 <= point.y() < 140+i*52:
                new = self.step(k,self.draft[k],e.angleDelta().y() > 0)
                if new != self.draft[k]: self.draft[k] = new; self.changed(k); self.update()
                return

    def paintEvent(self, event):
        p = self.begin(self.TITLE)
        for i,(k,label,unit) in enumerate(self.STEPPERS):
            y = 88+i*52
            draw_text(p,(29,y+12,300,28),label,19)
            for sign,glyph in (('-','minus'),('+','plus')):
                on = self.enabled(k+sign); r = self.buttons[k+sign]
                draw_circle(p,r,self.hover==k+sign,enabled=on); draw_glyph(p,r,glyph,on)
            value = self.draft[k]
            shown = ('Off' if not value else goal_label(value)) if k == 'goal' else str(value)
            draw_text(p,(387,y+10,104,32),shown,20,bold=True,align=CENTER)
            draw_text(p,(387,y+34,104,18),'' if k == 'goal' and not value else unit,11,MUTED,align=CENTER)
        p.setPen(QPen(QColor('#3b3b3b'),1)); p.drawLine(QPointF(29,412),QPointF(525,412))
        for i,(k,label) in enumerate(self.SWITCHES):
            y = 424+i*48; on = self.draft[k]
            draw_text(p,(29,y+6,400,28),label,19,TEXT if self.hover!=k else QColor('#ffffff'))
            track = QRectF(473,y+6,52,28); p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(BLUE if on else QColor('#4b4b4d')); p.drawRoundedRect(track,14,14)
            p.setBrush(TEXT); p.drawEllipse(QRectF(track.right()-25 if on else track.left()+3,y+9,22,22))
        p.setPen(QPen(QColor('#3b3b3b'),1)); p.drawLine(QPointF(29,628),QPointF(525,628))
        draw_text(p,(29,654,250,34),'Changing durations resets\nthe timer · work is kept',12,MUTED)
        draw_pill(p,self.buttons['cancel'],'Cancel',hover=self.hover=='cancel',size=16)
        r = self.buttons['save']; p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#25acff') if self.hover=='save' else BLUE); p.drawRoundedRect(r,21,21)
        draw_text(p,(r.x(),r.y()+4,r.width(),r.height()-8),'Save',16,TEXT,True,CENTER)
        p.end()


class HistoryPanel(Panel):
    H = 470
    TITLE = 'Focus History'

    def __init__(self, owner, key):
        super().__init__(owner, key)
        self.view = owner.ui.get('history_view') if owner.ui.get('history_view') in ('week','month') else 'week'
        self.offset_n = 0
        self.hover_bar = None
        self.buttons.update(week=QRectF(29,80,84,34), month=QRectF(121,80,92,34),
                            prev=QRectF(331,80,34,34), next=QRectF(491,80,34,34))

    def rows(self, offset=None):
        return period(self.owner.engine.days, self.view, self.offset_n if offset is None else offset, date.today())

    def enabled(self, key):
        if key == 'next': return self.offset_n < 0
        if key == 'prev':
            recorded = [d for d,v in self.owner.engine.days.items() if v.get('seconds',0) >= 30]
            return bool(recorded) and self.rows()[0][0].isoformat() > min(recorded)
        return True

    def activate(self, key):
        if key in ('week','month') and key != self.view:
            self.view, self.offset_n = key, 0
            self.owner.ui['history_view'] = key; self.owner.save_ui()
        elif key == 'prev': self.offset_n -= 1
        elif key == 'next': self.offset_n += 1
        else: super().activate(key); return
        self.update()

    def range_label(self, rows):
        first, last = rows[0][0], rows[-1][0]
        if self.view == 'month':
            return f'{first:%B}' if first.year == date.today().year else f'{first:%b %Y}'
        if first.month == last.month: return f'{first.day}–{last.day} {last:%b}'
        return f'{first.day} {first:%b} – {last.day} {last:%b}'

    def bar_geometry(self, count):
        col = 496/count
        width = 34 if count == 7 else min(11, col-4)
        return col, width

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        if self.offset is not None: return
        point = self.local(e.position()); rows = self.rows(); col, _ = self.bar_geometry(len(rows))
        bar = int((point.x()-29)//col) if 29 <= point.x() < 525 and 214 <= point.y() <= 400 else None
        if bar != self.hover_bar: self.hover_bar = bar; self.update()
    def leaveEvent(self, e):
        self.hover_bar = None; super().leaveEvent(e); self.update()

    def paintEvent(self, event):
        p = self.begin(self.TITLE)
        rows = self.rows(); today = date.today()
        for key,label in (('week','Week'),('month','Month')):
            draw_pill(p,self.buttons[key],label,self.view==key,self.hover==key)
        for key in ('prev','next'):
            on = self.enabled(key); draw_circle(p,self.buttons[key],self.hover==key,enabled=on); draw_glyph(p,self.buttons[key],key,on)
        draw_text(p,(365,84,126,26),self.range_label(rows),15,align=CENTER)
        # summary; the average counts only days that have already happened
        elapsed = [r for r in rows if r[0] <= today] or rows
        total = sum(r[1] for r in rows); sessions = sum(r[2] for r in rows)
        caption = {('week',0):'This week',('week',-1):'Last week',('month',0):'This month',('month',-1):'Last month'}
        draw_text(p,(29,132,300,22),caption.get((self.view,self.offset_n),'Total'),15,MUTED)
        draw_text(p,(27,150,320,56),hm(total),44,bold=True)
        draw_text(p,(29,138,496,22),plural(sessions,'session'),15,MUTED,align=RIGHT)
        draw_text(p,(29,164,496,26),f'Avg {hm(total/len(elapsed))} / day',19,align=RIGHT)
        # bars: scale to the busiest day, never below one focus session
        top, bottom = 250, 366
        goal = self.owner.engine.settings['goal']*60
        peak = max([r[1] for r in rows] + [self.owner.engine.settings['focus']*60, goal])
        col, width = self.bar_geometry(len(rows)); week = len(rows) == 7
        radius = 9 if week else width/2
        for i,(day,secs,_) in enumerate(rows):
            cx = 29+col*i+col/2; is_today = day == today; hot = i == self.hover_bar
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#383838' if hot else '#2c2c2c')); p.drawRoundedRect(QRectF(cx-width/2,top,width,bottom-top),radius,radius)
            if secs >= 30:
                h = max(width if not week else 10,(bottom-top)*secs/peak)
                p.setBrush(QColor('#25acff') if hot else BLUE if is_today else QColor('#0a7fc9'))
                p.drawRoundedRect(QRectF(cx-width/2,bottom-h,width,h),radius,radius)
            if week:
                draw_text(p,(cx-col/2,top-30,col,22),f'{secs/3600:.1f}h' if secs >= 30 else '–',13,TEXT if secs>=30 else MUTED,align=CENTER)
                draw_text(p,(cx-col/2,bottom+8,col,22),'Today' if is_today else f'{day:%a}',14,TEXT if is_today else MUTED,is_today,CENTER)
            elif is_today or (day.day in (1,8,15,22,29) and not (rows[0][0] <= today <= rows[-1][0] and abs((day-today).days) < 3)):
                draw_text(p,(cx-12,bottom+8,24,22),str(day.day),13,TEXT if is_today else MUTED,is_today,CENTER)
        if goal:
            gy = bottom-(bottom-top)*goal/peak
            p.setPen(QPen(QColor(104,199,255,170),1.5,Qt.PenStyle.DashLine)); p.drawLine(QPointF(29,gy),QPointF(525,gy))
            draw_text(p,(29,top-54,496,20),f'Goal {goal_label(goal//60)}',12,QColor('#68c7ff'),align=RIGHT)
        # footer: hovered day detail, otherwise best day in view + running streak
        p.setPen(QPen(QColor('#3b3b3b'),1)); p.drawLine(QPointF(29,412),QPointF(525,412))
        if self.hover_bar is not None and self.hover_bar < len(rows):
            day, secs, n = rows[self.hover_bar]
            draw_text(p,(29,422,496,27),f'{day:%a %d %b}  ·  {hm(secs)}  ·  {plural(n,"session")}',16,TEXT)
        else:
            best = max(rows, key=lambda r: r[1])
            draw_text(p,(29,422,300,27),f'Best  {best[0]:%a %d} · {hm(best[1])}' if best[1] >= 60 else 'Best  –',16,MUTED)
            s = streak(self.owner.engine.days, today, goal or 60)
            draw_text(p,(29,422,496,27),f'Streak  {plural(s,"day")}',16,MUTED,align=RIGHT)
        p.end()


def main():
    preview='--preview' in sys.argv
    if preview: os.environ['QT_QPA_PLATFORM']='offscreen'
    app=QApplication(sys.argv[:1]);app.setApplicationName('Focus Timer')
    for name in ('segoeui.ttf','seguisb.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    (ROOT/'state').mkdir(exist_ok=True)
    lock=QLockFile(str(ROOT/'state'/'focus.lock'))
    if not preview and not lock.tryLock(0): return
    widget=FocusWidget(preview)
    if preview:
        img=QImage(widget.width()*2,widget.height()*2,QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(2);img.fill(Qt.GlobalColor.transparent)
        painter=QPainter(img);widget.render(painter,QPoint());painter.end()
        target=Path(sys.argv[sys.argv.index('--preview')+1]);target.parent.mkdir(exist_ok=True,parents=True)
        assert img.save(str(target));return
    app.aboutToQuit.connect(widget.save)
    target = widget.pos()
    widget.show()
    QTimer.singleShot(500, lambda: (widget.move(target), widget.clamp(), widget.save()))
    app.exec()

if __name__=='__main__':main()
