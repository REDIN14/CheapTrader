# Credits and Licences

CheapTrader is made with the work of many others. This page lists what it is built from and under which
licence each part is used. CheapTrader's own code is under the **MIT licence** (see `LICENSE` in the
repository).

---

## 1. TradingView Lightweight Charts

> TradingView Lightweight Charts™
> Copyright (c) 2026 TradingView, Inc.
> [https://www.tradingview.com/](https://www.tradingview.com/)

The charts are drawn by [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/),
used under the Apache License 2.0. The licence asks for the attribution above and a link to tradingview.com,
which is why this page and the About window carry them.

CheapTrader is an independent project. It is **not affiliated with, endorsed by or sponsored by TradingView**.
The look of its interface is inspired by TradingView's; no TradingView code or artwork other than the chart
library above is used.

---

## 2. MetaTrader 5

MetaTrader 5 is a trademark of **MetaQuotes Ltd**. CheapTrader talks to a MetaTrader 5 terminal that you
install yourself, through MetaQuotes' `MetaTrader5` Python package (MIT licence). CheapTrader is not
affiliated with, endorsed by or sponsored by MetaQuotes or any broker.

---

## 3. What is inside the program

### The page (JavaScript)

| Part | Licence | What for |
| --- | --- | --- |
| TradingView Lightweight Charts 5 | Apache-2.0 | the candlestick chart |
| fancy-canvas | MIT | canvas helper of the chart library |
| React and React DOM 18 | MIT | the user interface |
| scheduler | MIT | part of React |

### The program (Python)

| Part | Licence | What for |
| --- | --- | --- |
| Python 3.12 | PSF-2.0 | the language and its standard library |
| FastAPI | MIT | the web interface of the program |
| Starlette | BSD-3-Clause | web toolkit under FastAPI |
| Uvicorn | BSD-3-Clause | the web server |
| Pydantic, pydantic-settings | MIT | data models and settings |
| HTTPX, HTTPCore, h11, anyio | BSD-3-Clause / MIT | HTTP and async plumbing |
| websockets | BSD-3-Clause | the live connection to the page |
| httptools, watchfiles, PyYAML, python-dotenv, click | MIT / BSD-3-Clause | server helpers |
| pandas | BSD-3-Clause | candles as tables, for indicators |
| NumPy | BSD-3-Clause | numbers for indicators and replay |
| Matplotlib (with contourpy, cycler, fonttools, kiwisolver, pillow, pyparsing, python-dateutil, six) | PSF-based, BSD, MIT | chart snapshots |
| certifi | MPL-2.0 | certificate bundle |
| tzdata, packaging, typing-extensions, typing-inspection, annotated-types | Apache-2.0 / BSD / PSF / MIT | helpers |
| MetaTrader5 | MIT | the connection to the MetaTrader 5 terminal |

### The Windows program

[PyInstaller](https://pyinstaller.org/) packs the program into `CheapTrader.exe` (GPL-2.0 with the
exception that lets the programs it packs be distributed under any licence). The installer is built with
[Inno Setup](https://jrsoftware.org/isinfo.php).

---

## 4. The licences

The licence texts of the libraries are in their own packages and repositories; the main ones:

* Apache License 2.0: [https://www.apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0)
* MIT licence: [https://opensource.org/license/mit](https://opensource.org/license/mit)
* BSD 3-Clause: [https://opensource.org/license/bsd-3-clause](https://opensource.org/license/bsd-3-clause)
* Mozilla Public License 2.0 (certifi): [https://www.mozilla.org/MPL/2.0/](https://www.mozilla.org/MPL/2.0/)
* PSF licence: [https://docs.python.org/3/license.html](https://docs.python.org/3/license.html)

---

## 5. Risk and warranty

Trading leveraged products carries a high risk of losing money. CheapTrader is provided "as is", without
warranty of any kind, and is not financial advice. Read the MIT licence for the full terms.
