"""US regular equity sessions, verified against exchange holiday/early-close rules."""
from datetime import date, timedelta
import exchange_calendars as xcals
import pandas as pd


class Calendar:
    def __init__(self, start, end):
        a = date.fromisoformat(start)-timedelta(days=20)
        b = date.fromisoformat(end)+timedelta(days=600)
        self.exchange = xcals.get_calendar('XNYS', start=str(a), end=str(b))
        self.sessions = [str(d.date()) for d in self.exchange.sessions_in_range(start,end)]

    def close(self, day):
        return self.exchange.session_close(day).tz_convert('America/New_York').isoformat()

    def previous(self, day):
        return str(self.exchange.previous_session(day).date())

    def next(self, day):
        return str(self.exchange.next_session(day).date())

    def week(self, day):
        d=date.fromisoformat(day)
        monday=d-timedelta(days=d.weekday())
        friday=monday+timedelta(days=4)
        first=str(self.exchange.date_to_session(str(monday),direction='next').date())
        adjusted=str(self.exchange.date_to_session(str(friday),direction='previous').date())
        return dict(monday=str(monday), friday=str(friday), first_session=first,
                    friday_last_session=adjusted)

    def signal(self, day):
        return pd.Timestamp(f'{day} 09:00',tz='America/New_York').isoformat()

    def weekly(self):
        return [dict(date=d, previous_session=self.previous(d), signal_at=self.signal(d),
                     closing_reference=self.close(d), **self.week(d))
                for d in self.sessions if self.week(d)['first_session']==d]
