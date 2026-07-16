import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import habits
from agent.settings import TZ

CFG = {"habit_titles": ["Gym", "Sleep"], "sleep": {"start": "01:00", "end": "08:30"}}
DAY = date(2026, 7, 17)


def ev(title, start_hm, end_hm, all_day=False, dayrunly=False, day=DAY):
    if all_day:
        return {"id": title, "title": title, "all_day": True, "is_dayrunly": dayrunly,
                "start": datetime.combine(day, datetime.min.time(), tzinfo=TZ),
                "end": datetime.combine(day, datetime.min.time(), tzinfo=TZ)}
    sh, sm = map(int, start_hm.split(":"))
    eh, em = map(int, end_hm.split(":"))
    return {"id": title, "title": title, "all_day": False, "is_dayrunly": dayrunly,
            "start": datetime(day.year, day.month, day.day, sh, sm, tzinfo=TZ),
            "end": datetime(day.year, day.month, day.day, eh, em, tzinfo=TZ)}


class TestFreeSlots(unittest.TestCase):
    def test_empty_day_is_one_big_slot(self):
        slots = habits.free_slots([], DAY, CFG)
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0][0].hour, 8)
        self.assertEqual(slots[0][1].day, 18)  # bed at 01:00 next day

    def test_packed_day_has_no_slots(self):
        events = [ev("Work", "08:30", "18:00"), ev("Dinner", "18:00", "23:00"),
                  ev("Movie", "23:00", "23:59")]
        slots = habits.free_slots(events, DAY, CFG, min_minutes=90)
        self.assertEqual(slots, [])

    def test_gap_between_meetings_found(self):
        events = [ev("Standup", "09:00", "10:00"), ev("Review", "12:00", "13:00")]
        slots = habits.free_slots(events, DAY, CFG)
        self.assertIn((events[0]["end"], events[1]["start"]), slots)

    def test_all_day_events_do_not_block(self):
        slots = habits.free_slots([ev("Birthday", None, None, all_day=True)], DAY, CFG)
        self.assertEqual(len(slots), 1)

    def test_slots_never_start_before_wake(self):
        for s, _ in habits.free_slots([ev("Early", "05:00", "09:00")], DAY, CFG):
            self.assertGreaterEqual(s.hour, 9)


class TestPickSlot(unittest.TestCase):
    def test_picks_first_fitting(self):
        slots = habits.free_slots([ev("A", "09:00", "12:00")], DAY, CFG)
        start, end = habits.pick_slot(slots, 30)
        self.assertEqual((start.hour, start.minute), (8, 30))
        self.assertEqual((end - start).seconds, 1800)

    def test_respects_not_before(self):
        slots = habits.free_slots([], DAY, CFG)
        nb = datetime(2026, 7, 17, 15, 0, tzinfo=TZ)
        start, _ = habits.pick_slot(slots, 30, not_before=nb)
        self.assertEqual(start, nb)

    def test_none_when_nothing_fits(self):
        self.assertIsNone(habits.pick_slot([], 30))


class TestHabitGuardian(unittest.TestCase):
    def test_meeting_over_gym_detected(self):
        gym, meeting = ev("Gym", "18:00", "19:00"), ev("Sync call", "18:30", "19:30")
        collisions = habits.find_collisions([gym, meeting], CFG)
        self.assertEqual(collisions, [(gym, meeting)])

    def test_dayrunly_events_never_collide(self):
        gym = ev("Gym", "18:00", "19:00")
        mine = ev("[Dayrunly] Read rundown", "18:00", "18:15", dayrunly=True)
        self.assertEqual(habits.find_collisions([gym, mine], CFG), [])

    def test_event_inside_sleep_flagged(self):
        late = ev("Deploy party", "23:30", "23:59")
        night = {"id": "n", "title": "Night call", "all_day": False, "is_dayrunly": False,
                 "start": datetime(2026, 7, 18, 2, 0, tzinfo=TZ),
                 "end": datetime(2026, 7, 18, 3, 0, tzinfo=TZ)}
        flagged = habits.events_in_sleep([late, night], DAY, CFG)
        self.assertEqual(flagged, [night])

    def test_reschedule_finds_next_slot(self):
        gym, meeting = ev("Gym", "18:00", "19:00"), ev("Sync", "17:30", "20:00")
        slot = habits.reschedule_slot(gym, [gym, meeting], DAY, CFG)
        self.assertIsNotNone(slot)
        self.assertGreaterEqual(slot[0], meeting["end"])
        self.assertEqual((slot[1] - slot[0]).seconds, 3600)

    def test_habit_match_case_insensitive(self):
        self.assertTrue(habits.is_habit("  gym ", CFG))
        self.assertFalse(habits.is_habit("Gym prep", CFG))


if __name__ == "__main__":
    unittest.main()
