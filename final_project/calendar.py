"""Actual XNYS sessions, including holidays and early closes."""
from datetime import timedelta
import exchange_calendars as xcals
import pandas as pd


def exchange(day):
    d = pd.Timestamp(day).date()
    return xcals.get_calendar('XNYS', start=str(d - timedelta(days=370)),
                             end=str(d + timedelta(days=40)))


def context(now):
    clock = pd.Timestamp(now)
    if clock.tzinfo is None:
        raise ValueError('Run timestamp must be timezone-aware')
    clock = clock.tz_convert('UTC')
    cal = exchange(clock)
    recent = cal.sessions_in_range(str(clock.date() - timedelta(days=14)), str(clock.date()))
    completed = [d for d in recent if cal.session_close(d) <= clock]
    if not completed:
        raise ValueError('No completed exchange session')
    last = completed[-1]
    target = cal.next_session(last)
    if clock >= cal.session_open(target):
        raise ValueError('Next session is already open; nightly planning is blocked')
    monday = target.date() - timedelta(days=target.weekday())
    first = cal.date_to_session(str(monday), direction='next')
    return {'as_of': str(last.date()), 'target_session': str(target.date()),
            'first_session_of_week': target == first, 'exchange': 'XNYS',
            'close_time': cal.session_close(last).isoformat()}


def required_sessions(as_of, count=50):
    cal = exchange(as_of)
    end = cal.sessions.get_loc(pd.Timestamp(as_of))
    return [str(x.date()) for x in cal.sessions[end-count+1:end+1]]
