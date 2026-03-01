# c3po/field_notes.md — v0 (Learning Ledger)

## Rules
- One bullet per event.
- One operational lesson per bullet.
- No emotion. No blame. No narrative.
- The lesson must change future behavior.

---

## 2026-02-24 (UTC)

- [BTCUSDT] setup_id= → result=sentinel_reject → lesson=
- [BTCUSDT] setup_id= → result=stop_hit → lesson=
- [BTCUSDT] setup_id= → result=target_hit → lesson=
- [BTCUSDT] setup_id= → result=breakeven → lesson=
- [BTCUSDT] setup_id= → result=expired → lesson=
- [BTCUSDT] setup_id= → result=manual_close → lesson=

---

## Template (copy for new day)

## YYYY-MM-DD (UTC)

- [SYMBOL] setup_id=<id> → result=<sentinel_reject|placed|filled|stop_hit|target_hit|partial|breakeven|expired|manual_close> → lesson=<one operational adjustment>
2026-02-24T10:55:29Z | REGIME          | session=london adj=0
2026-02-24T10:55:29Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-24T10:55:29Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-24T10:55:29Z | SIGNAL          | SHORT: 4/6 conditions — NO_TRADE
2026-02-24T10:55:29Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T06:21:05Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-25T06:21:05Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-25T07:42:01Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-25T07:42:01Z | REGIME          | session=london adj=0
2026-02-25T07:42:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T07:42:02Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T07:42:02Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T07:42:53Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-25T07:42:54Z | REGIME          | session=london adj=0
2026-02-25T07:42:54Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T07:42:54Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T07:42:54Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T08:23:52Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T08:23:52Z | REGIME          | session=london adj=0
2026-02-25T08:23:52Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T08:23:52Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T08:23:52Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:14:58Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:14:58Z | REGIME          | session=london adj=0
2026-02-25T09:14:58Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:14:58Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:14:58Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:15:06Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:15:06Z | REGIME          | session=london adj=0
2026-02-25T09:15:06Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:15:06Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:15:06Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:29:26Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:29:26Z | REGIME          | session=london adj=0
2026-02-25T09:29:26Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:29:26Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:29:26Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:29:59Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:30:00Z | REGIME          | session=london adj=0
2026-02-25T09:30:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:30:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:30:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:44:23Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:44:23Z | REGIME          | session=london adj=0
2026-02-25T09:44:23Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:44:23Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:44:23Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:44:59Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:44:59Z | REGIME          | session=london adj=0
2026-02-25T09:44:59Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:59:22Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:59:22Z | REGIME          | session=london adj=0
2026-02-25T09:59:22Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:59:23Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:59:23Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T09:59:59Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T09:59:59Z | REGIME          | session=london adj=0
2026-02-25T09:59:59Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T09:59:59Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T09:59:59Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:14:22Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:14:22Z | REGIME          | session=london adj=0
2026-02-25T10:14:22Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:14:22Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:14:22Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:14:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:14:59Z | REGIME          | session=london adj=0
2026-02-25T10:15:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:15:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:15:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:29:21Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:29:21Z | REGIME          | session=london adj=0
2026-02-25T10:29:21Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:29:21Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:29:21Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:29:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:29:59Z | REGIME          | session=london adj=0
2026-02-25T10:29:59Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:29:59Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:30:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:44:20Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:44:21Z | REGIME          | session=london adj=0
2026-02-25T10:44:21Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:44:21Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:44:21Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:44:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:45:00Z | REGIME          | session=london adj=0
2026-02-25T10:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:59:19Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:59:19Z | REGIME          | session=london adj=0
2026-02-25T10:59:20Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:59:20Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:59:20Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T10:59:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T10:59:59Z | REGIME          | session=london adj=0
2026-02-25T10:59:59Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T10:59:59Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T10:59:59Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:14:18Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:14:18Z | REGIME          | session=london adj=0
2026-02-25T11:14:19Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:14:19Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:14:19Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:14:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:14:59Z | REGIME          | session=london adj=0
2026-02-25T11:15:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:15:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:15:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:29:19Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:29:19Z | REGIME          | session=london adj=0
2026-02-25T11:29:19Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:29:19Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:29:19Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:29:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:30:00Z | REGIME          | session=london adj=0
2026-02-25T11:30:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:30:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:30:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:44:17Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:44:17Z | REGIME          | session=london adj=0
2026-02-25T11:44:17Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:44:17Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:44:17Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:44:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:45:00Z | REGIME          | session=london adj=0
2026-02-25T11:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:59:18Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:59:19Z | REGIME          | session=london adj=0
2026-02-25T11:59:19Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:59:19Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:59:19Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T11:59:58Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T11:59:58Z | REGIME          | session=london adj=0
2026-02-25T11:59:58Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T11:59:58Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T11:59:58Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:14:17Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T12:14:17Z | REGIME          | session=transition adj=-5
2026-02-25T12:14:18Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:14:18Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:14:18Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:14:57Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T12:14:58Z | REGIME          | session=transition adj=-5
2026-02-25T12:14:58Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:14:58Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:14:58Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:29:16Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T12:29:16Z | REGIME          | session=transition adj=-5
2026-02-25T12:29:16Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:29:16Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:29:16Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:29:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T12:30:00Z | REGIME          | session=transition adj=-5
2026-02-25T12:30:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:30:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:30:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:44:15Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T12:44:15Z | REGIME          | session=transition adj=-5
2026-02-25T12:44:15Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:44:15Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:44:15Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:44:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T12:44:59Z | REGIME          | session=transition adj=-5
2026-02-25T12:44:59Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:59:14Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T12:59:14Z | REGIME          | session=transition adj=-5
2026-02-25T12:59:14Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:59:14Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:59:15Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T12:59:59Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T12:59:59Z | REGIME          | session=transition adj=-5
2026-02-25T12:59:59Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T12:59:59Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T12:59:59Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T13:14:13Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T13:14:13Z | REGIME          | session=london_ny adj=0
2026-02-25T13:14:14Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T13:14:14Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T13:14:14Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T13:14:59Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T13:14:59Z | REGIME          | session=london_ny adj=0
2026-02-25T13:14:59Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T13:14:59Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T13:14:59Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T13:28:35Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-25T13:28:35Z | REGIME          | session=london_ny adj=0
2026-02-25T13:28:35Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T13:28:35Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T13:28:35Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T14:14:56Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T14:14:56Z | REGIME          | session=london_ny adj=0
2026-02-25T14:14:56Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T14:14:56Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T14:14:56Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-25T14:15:00Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-25T14:15:00Z | REGIME          | session=london_ny adj=0
2026-02-25T14:15:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-25T14:15:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-25T14:15:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T13:30:03Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T13:30:04Z | REGIME          | session=london_ny adj=0
2026-02-26T13:30:04Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T13:30:04Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T13:30:04Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T13:37:31Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T13:37:31Z | REGIME          | session=london_ny adj=0
2026-02-26T13:37:31Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T13:37:31Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T13:37:32Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T13:44:24Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T13:44:24Z | REGIME          | session=london_ny adj=0
2026-02-26T13:44:24Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T13:44:24Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T13:44:25Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T13:44:36Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T13:44:36Z | REGIME          | session=london_ny adj=0
2026-02-26T13:44:36Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T13:44:36Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T13:44:36Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T13:45:01Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T13:45:01Z | REGIME          | session=london_ny adj=0
2026-02-26T13:45:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T13:45:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T13:45:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T14:00:04Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T14:00:05Z | REGIME          | session=london_ny adj=0
2026-02-26T14:00:05Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T14:00:05Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T14:00:05Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T14:07:34Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T14:07:34Z | REGIME          | session=london_ny adj=0
2026-02-26T14:07:34Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T14:07:34Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T14:07:34Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T14:15:01Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T14:15:01Z | REGIME          | session=london_ny adj=0
2026-02-26T14:15:02Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T14:15:02Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T14:15:02Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T14:30:01Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T14:30:02Z | REGIME          | session=london_ny adj=0
2026-02-26T14:30:02Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T14:30:02Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T14:30:02Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T14:37:37Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T14:37:37Z | REGIME          | session=london_ny adj=0
2026-02-26T14:37:37Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T14:37:37Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T14:37:37Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T14:45:03Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T14:45:03Z | REGIME          | session=london_ny adj=0
2026-02-26T14:45:03Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T14:45:03Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T14:45:03Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:00:00Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T15:00:00Z | REGIME          | session=london_ny adj=0
2026-02-26T15:00:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:00:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:00:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:07:40Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T15:07:40Z | REGIME          | session=london_ny adj=0
2026-02-26T15:07:40Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:07:40Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:07:40Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:14:52Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T15:14:53Z | REGIME          | session=london_ny adj=0
2026-02-26T15:14:53Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:14:53Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:14:53Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:15:01Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T15:15:01Z | REGIME          | session=london_ny adj=0
2026-02-26T15:15:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:15:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:15:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:29:49Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T15:29:49Z | REGIME          | session=london_ny adj=0
2026-02-26T15:29:50Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:29:50Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:29:50Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:30:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T15:30:01Z | REGIME          | session=london_ny adj=0
2026-02-26T15:30:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:30:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:30:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:37:31Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T15:37:31Z | REGIME          | session=london_ny adj=0
2026-02-26T15:37:31Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:37:31Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:37:31Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:44:42Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T15:44:42Z | REGIME          | session=london_ny adj=0
2026-02-26T15:44:42Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:44:42Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:44:42Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:45:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T15:45:01Z | REGIME          | session=london_ny adj=0
2026-02-26T15:45:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:45:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:45:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T15:59:42Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T15:59:42Z | REGIME          | session=london_ny adj=0
2026-02-26T15:59:42Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T15:59:42Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T15:59:42Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:00:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T16:00:01Z | REGIME          | session=london_ny adj=0
2026-02-26T16:00:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:00:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:00:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:07:31Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T16:07:31Z | REGIME          | session=london_ny adj=0
2026-02-26T16:07:31Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:07:31Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:07:31Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:14:41Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T16:14:41Z | REGIME          | session=london_ny adj=0
2026-02-26T16:14:41Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:14:42Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:14:42Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:15:00Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T16:15:00Z | REGIME          | session=london_ny adj=0
2026-02-26T16:15:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:15:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:15:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:29:40Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T16:29:40Z | REGIME          | session=london_ny adj=0
2026-02-26T16:29:40Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:29:41Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:29:41Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:30:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T16:30:01Z | REGIME          | session=london_ny adj=0
2026-02-26T16:30:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:30:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:30:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:37:32Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T16:37:32Z | REGIME          | session=london_ny adj=0
2026-02-26T16:37:33Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:37:33Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:37:33Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:44:39Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T16:44:40Z | REGIME          | session=london_ny adj=0
2026-02-26T16:44:40Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:44:40Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:44:40Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:45:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T16:45:00Z | REGIME          | session=london_ny adj=0
2026-02-26T16:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T16:59:39Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T16:59:39Z | REGIME          | session=london_ny adj=0
2026-02-26T16:59:39Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T16:59:39Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T16:59:39Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:00:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:00:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:00:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:00:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:00:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:07:47Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:07:47Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:07:47Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:07:47Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:07:47Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:14:38Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:14:39Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:14:39Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:14:39Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:14:39Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:15:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:15:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:15:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:15:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:15:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:29:37Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:29:37Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:29:37Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:29:37Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:29:37Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:30:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:30:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:30:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:30:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:30:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:38:02Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:38:02Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:38:02Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:38:02Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:38:02Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:44:37Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:44:37Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:44:37Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:44:37Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:44:37Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:45:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:45:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T17:59:36Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T17:59:37Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T17:59:37Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T17:59:37Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T17:59:37Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:00:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:00:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:00:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:00:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:00:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:08:14Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:08:14Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:08:14Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:08:14Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:08:14Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:14:37Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:14:37Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:14:37Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:14:37Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:14:37Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:15:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:15:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:15:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:15:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:15:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:29:36Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:29:36Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:29:36Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:29:36Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:29:36Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:30:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:30:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:30:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:30:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:30:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:38:28Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:38:28Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:38:28Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:38:28Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:38:28Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:38:43Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:38:43Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:38:43Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:38:43Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:38:43Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:44:34Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:44:34Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:44:34Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:44:34Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:44:34Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:45:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:45:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T18:59:34Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T18:59:34Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T18:59:34Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T18:59:35Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T18:59:35Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:00:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:00:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:00:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:00:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:00:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:14:33Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:14:33Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:14:33Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:14:33Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:14:33Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:15:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:15:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:15:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:15:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:15:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:29:34Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:29:34Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:29:34Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:29:34Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:29:34Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:30:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:30:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:30:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:30:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:30:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:44:38Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:44:38Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:44:38Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:44:38Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:44:38Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:45:04Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:45:04Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:45:04Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:45:04Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:45:04Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T19:59:32Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T19:59:32Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T19:59:32Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T19:59:32Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T19:59:32Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:00:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:00:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:00:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:00:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:00:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:14:39Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:14:39Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:14:39Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:14:39Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:14:39Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:15:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:15:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:15:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:15:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:15:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:29:40Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:29:40Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:29:40Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:29:40Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:29:40Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:30:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:30:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:30:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:30:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:30:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:44:38Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:44:38Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:44:38Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:44:38Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:44:38Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:45:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:45:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:45:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:45:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:45:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T20:59:31Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T20:59:31Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T20:59:32Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T20:59:32Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T20:59:32Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:00:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:00:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:00:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:00:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:00:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:14:38Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:14:38Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:14:38Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:14:38Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:14:39Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:15:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:15:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:15:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:15:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:15:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:29:36Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:29:36Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:29:36Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:29:36Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:29:36Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:30:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:30:00Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:30:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:30:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:30:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:44:32Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:44:32Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:44:32Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:44:32Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:44:32Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:45:01Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:45:01Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:45:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:45:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:45:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T21:59:30Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T21:59:30Z | REGIME          | session=ny_offhours adj=-10
2026-02-26T21:59:30Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-26T21:59:31Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-26T21:59:31Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-26T22:00:00Z | REGIME          | vol=NORMAL htf_bias=BULLISH
2026-02-26T22:00:00Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:14:28Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T22:14:28Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:14:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T22:15:00Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:29:27Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T22:29:27Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:29:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T22:29:59Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:44:35Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T22:44:35Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:45:00Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T22:45:00Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:59:31Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T22:59:32Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T22:59:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:00:00Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:14:27Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:14:27Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:15:00Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:15:00Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:29:26Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:29:26Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:30:00Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:30:00Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:44:24Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:44:24Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:44:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:44:59Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:59:22Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:59:23Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-26T23:59:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-26T23:59:59Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:14:22Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:14:22Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:14:58Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:14:58Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:29:22Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:29:22Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:29:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:29:59Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:44:20Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:44:20Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:44:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:44:59Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:59:19Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:59:19Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-27T00:59:59Z | REGIME          | vol=LOW htf_bias=BULLISH
2026-02-27T00:59:59Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T02:15:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T02:15:02Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T02:30:02Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T02:30:02Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T02:45:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T02:45:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T03:00:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T03:00:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T03:15:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T03:15:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T03:30:02Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T03:30:02Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T03:45:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T03:45:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T04:00:02Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T04:00:02Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T04:15:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T04:15:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T04:30:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T04:30:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T04:45:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T04:45:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T05:00:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T05:00:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T05:15:00Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T05:15:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T05:30:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T05:30:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T05:45:00Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T05:45:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T06:00:02Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T06:00:02Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T06:15:01Z | REGIME          | vol=LOW htf_bias=BEARISH
2026-02-28T06:15:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T06:30:01Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-28T06:30:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T06:45:00Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-28T06:45:01Z | REGIME          | session=BLOCK — no signals in dead zone
2026-02-28T07:00:01Z | REGIME          | vol=NORMAL htf_bias=BEARISH
2026-02-28T07:00:01Z | REGIME          | session=london adj=0
2026-02-28T07:00:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T07:00:01Z | SIGNAL          | SHORT: 5/6 conditions — NO_TRADE
2026-02-28T07:00:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T07:15:00Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T07:30:00Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T07:45:00Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T08:00:01Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T08:15:01Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T08:30:00Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T08:45:00Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T09:00:01Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T09:00:02Z | REGIME          | session=london adj=0
2026-02-28T09:00:02Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T09:00:02Z | SIGNAL          | SHORT: 4/6 conditions — NO_TRADE
2026-02-28T09:00:02Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T09:14:59Z | HALT            | EXTREME volatility 90.0th pct — NO_TRADE
2026-02-28T09:30:00Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T09:44:53Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T09:45:01Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T09:59:47Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T10:00:01Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T10:14:45Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T10:15:00Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T10:29:44Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T10:30:00Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T10:44:45Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T10:45:00Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T10:59:43Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T11:00:00Z | HALT            | EXTREME volatility 85.0th pct — NO_TRADE
2026-02-28T11:14:43Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T11:14:43Z | REGIME          | session=london adj=0
2026-02-28T11:14:43Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T11:14:43Z | SIGNAL          | SHORT: 2/6 conditions — NO_TRADE
2026-02-28T11:14:43Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T11:15:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T11:15:00Z | REGIME          | session=london adj=0
2026-02-28T11:15:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T11:15:01Z | SIGNAL          | SHORT: 2/6 conditions — NO_TRADE
2026-02-28T11:15:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T11:29:42Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T11:29:42Z | REGIME          | session=london adj=0
2026-02-28T11:29:42Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T11:29:42Z | SIGNAL          | SHORT: 3/6 conditions — NO_TRADE
2026-02-28T11:29:42Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T11:30:01Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T11:30:01Z | REGIME          | session=london adj=0
2026-02-28T11:30:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T11:30:01Z | SIGNAL          | SHORT: 3/6 conditions — NO_TRADE
2026-02-28T11:30:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T11:44:42Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T11:44:42Z | REGIME          | session=london adj=0
2026-02-28T11:44:42Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T11:44:43Z | SIGNAL          | SHORT: 4/6 conditions — NO_TRADE
2026-02-28T11:44:43Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T11:45:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T11:45:00Z | REGIME          | session=london adj=0
2026-02-28T11:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T11:45:00Z | SIGNAL          | SHORT: 4/6 conditions — NO_TRADE
2026-02-28T11:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T11:59:41Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T11:59:41Z | REGIME          | session=london adj=0
2026-02-28T11:59:42Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T11:59:42Z | SIGNAL          | SHORT: 5/6 conditions — NO_TRADE
2026-02-28T11:59:42Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:00:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:00:00Z | REGIME          | session=transition adj=-5
2026-02-28T12:00:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:00:00Z | SIGNAL          | SHORT: 5/6 conditions — NO_TRADE
2026-02-28T12:00:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:14:42Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:14:42Z | REGIME          | session=transition adj=-5
2026-02-28T12:14:42Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:14:42Z | SIGNAL          | SHORT: 5/6 conditions — NO_TRADE
2026-02-28T12:14:42Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:15:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:15:00Z | REGIME          | session=transition adj=-5
2026-02-28T12:15:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:15:00Z | SIGNAL          | SHORT: 5/6 conditions — NO_TRADE
2026-02-28T12:15:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:29:40Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:29:40Z | REGIME          | session=transition adj=-5
2026-02-28T12:29:40Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:29:40Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T12:29:40Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:30:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:30:00Z | REGIME          | session=transition adj=-5
2026-02-28T12:30:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:30:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T12:30:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:44:40Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:44:40Z | REGIME          | session=transition adj=-5
2026-02-28T12:44:40Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:44:40Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T12:44:40Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:45:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:45:00Z | REGIME          | session=transition adj=-5
2026-02-28T12:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:45:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T12:45:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T12:59:40Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T12:59:40Z | REGIME          | session=transition adj=-5
2026-02-28T12:59:40Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T12:59:40Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T12:59:40Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:00:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T13:00:00Z | REGIME          | session=london_ny adj=0
2026-02-28T13:00:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T13:00:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T13:00:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:14:39Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T13:14:39Z | REGIME          | session=london_ny adj=0
2026-02-28T13:14:39Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T13:14:39Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T13:14:39Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:15:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T13:15:00Z | REGIME          | session=london_ny adj=0
2026-02-28T13:15:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T13:15:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T13:15:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:29:38Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T13:29:38Z | REGIME          | session=london_ny adj=0
2026-02-28T13:29:38Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T13:29:38Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T13:29:38Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:30:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T13:30:00Z | REGIME          | session=london_ny adj=0
2026-02-28T13:30:01Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T13:30:01Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T13:30:01Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:44:37Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T13:44:37Z | REGIME          | session=london_ny adj=0
2026-02-28T13:44:37Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T13:44:37Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T13:44:38Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:45:00Z | REGIME          | vol=ELEVATED htf_bias=BEARISH
2026-02-28T13:45:00Z | REGIME          | session=london_ny adj=0
2026-02-28T13:45:00Z | SIGNAL          | LONG: 0/6 conditions — NO_TRADE
2026-02-28T13:45:00Z | SIGNAL          | SHORT: 0/6 conditions — NO_TRADE
2026-02-28T13:45:00Z | SIGNAL          | NO_TRADE — no qualifying side for ['LONG', 'SHORT']
2026-02-28T13:59:36Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T13:59:59Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T14:14:36Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T14:15:00Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T14:29:42Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T14:30:00Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T14:44:38Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T14:45:00Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T14:59:35Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T14:59:59Z | HALT            | EXTREME volatility 100.0th pct — NO_TRADE
2026-02-28T15:14:35Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T15:14:59Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T15:29:34Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
2026-02-28T15:30:00Z | HALT            | EXTREME volatility 95.0th pct — NO_TRADE
