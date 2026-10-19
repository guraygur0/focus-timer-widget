import tempfile
import unittest
from pathlib import Path
from datetime import date, datetime
from focus_engine import FocusTimer, period, streak
class TimerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.json';self.t=FocusTimer(self.path)
    def advance(self,seconds):
        self.t.last=0;self.t.running=True
        return self.t.tick(seconds,datetime(2026,9,28,12).timestamp())
    def test_defaults(self):
        self.assertEqual([self.t.settings[k] for k in ('focus','short','long','every')],[90,15,30,3])
    def test_only_focus_counts(self):
        self.advance(2);self.t.switch('short');self.advance(2)
        self.assertEqual(self.t.days['2026-09-28']['seconds'],2)
    def test_sleep_not_counted(self):
        self.advance(100);self.assertFalse(self.t.running);self.assertEqual(self.t.days,{})
    def test_third_focus_long_break(self):
        self.t.cycle=2;self.t.remaining=1;self.assertTrue(self.advance(2))
        self.assertEqual(self.t.mode,'long');self.assertEqual(self.t.remaining,1800)
        self.assertEqual(self.t.days['2026-09-28']['seconds'],1)
    def test_restart_paused_and_work_preserved(self):
        self.advance(2);self.t.save();t=FocusTimer(self.path)
        self.assertFalse(t.running);self.assertEqual(t.remaining,5398);self.assertEqual(t.days,self.t.days)
    def test_midnight_split(self):
        self.t.add_work(4,datetime(2026,9,29,0,0,2).timestamp())
        self.assertEqual(self.t.days['2026-09-28']['seconds'],2)
        self.assertEqual(self.t.days['2026-09-29']['seconds'],2)
    def test_bad_state(self):
        self.path.write_text('{"settings":{"focus":-1},"remaining":NaN}')
        t=FocusTimer(self.path);self.assertEqual(t.remaining,5400)
    def test_reset_preserves_total(self):
        self.advance(2);self.t.reset();self.assertEqual(self.t.days['2026-09-28']['seconds'],2)
    def test_old_days_survive_save(self):
        self.t.days['2024-01-15']=dict(seconds=3600,sessions=1);self.t.save()
        self.assertEqual(FocusTimer(self.path).days['2024-01-15']['seconds'],3600)
    def test_week_period_starts_monday(self):
        rows=period({'2026-09-22':{'seconds':60,'sessions':1}},'week',0,date(2026,9,28))
        self.assertEqual((rows[0][0],rows[-1][0]),(date(2026,9,28),date(2026,10,4)))
        rows=period({'2026-09-22':{'seconds':60,'sessions':1}},'week',-1,date(2026,9,28))
        self.assertEqual((rows[0][0],rows[1][1],rows[1][2]),(date(2026,9,21),60,1))
    def test_month_period_crosses_year(self):
        rows=period({},'month',-9,date(2026,9,28))
        self.assertEqual((rows[0][0],len(rows)),(date(2025,12,1),31))
        self.assertEqual(len(period({},'month',-7,date(2026,9,28))),28)
    def test_streak(self):
        d={'2026-09-26':{'seconds':600},'2026-09-27':{'seconds':600}}
        self.assertEqual(streak(d,date(2026,9,28)),2)
        d['2026-09-28']={'seconds':600};self.assertEqual(streak(d,date(2026,9,28)),3)
        self.assertEqual(streak(d,date(2026,9,30)),0)
    def test_new_settings_validated(self):
        self.path.write_text('{"settings":{"goal":900,"volume":-5,"notify":"yes"}}')
        t=FocusTimer(self.path);self.assertEqual((t.settings['goal'],t.settings['volume'],t.settings['notify']),(0,70,True))
    def test_skip_focus_advances_round_without_session(self):
        self.t.cycle=2;self.t.skip()
        self.assertEqual((self.t.mode,self.t.cycle,self.t.remaining,self.t.days),('long',3,1800,{}))
        self.t.skip();self.assertEqual((self.t.mode,self.t.remaining),('focus',5400))
    def test_extend(self):
        self.t.remaining=10;self.t.extend();self.assertEqual(self.t.remaining,310)
    def test_chimes_are_valid_wav(self):
        import chimes,wave
        paths=chimes.ensure(Path(self.tmp.name)/'sounds')
        self.assertEqual(sorted(paths),['focus','long','short'])
        for path in paths.values():
            with wave.open(str(path)) as f: self.assertEqual((f.getnchannels(),f.getframerate()),(1,44100));self.assertGreater(f.getnframes(),30000)
    def test_volume_scaling(self):
        import chimes,wave,io,array
        data=chimes.ensure(Path(self.tmp.name)/'s')['focus'].read_bytes()
        def peak(b):
            with wave.open(io.BytesIO(b)) as f: return max(abs(x) for x in array.array('h',f.readframes(f.getnframes())))
        self.assertAlmostEqual(peak(chimes.scaled(data,.5))/peak(data),.5,places=2)
if __name__=='__main__':unittest.main()
