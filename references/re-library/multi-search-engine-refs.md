# International Search Engine Deep Search Guide

## 🔍 Google Deep Search

### 1.1 Basic advanced search operators

| Operator | Function | Example | URL |
|--------|------|------|-----|
| `""` | Exact match | `"machine learning"` | `https://www.google.com/search?q=%22machine+learning%22` |
| `-` | Exclude keyword | `python -snake` | `https://www.google.com/search?q=python+-snake` |
| `OR` | OR operation | `machine learning OR deep learning` | `https://www.google.com/search?q=machine+learning+OR+deep+learning` |
| `*` | Wildcard | `machine * algorithms` | `https://www.google.com/search?q=machine+*+algorithms` |
| `()` | Grouping | `(apple OR microsoft) phones` | `https://www.google.com/search?q=(apple+OR+microsoft)+phones` |
| `..` | Number range | `laptop $500..$1000` | `https://www.google.com/search?q=laptop+%24500..%241000` |

### 1.2 Site and file search

| Operator | Function | Example |
|--------|------|------|
| `site:` | Search within a site | `site:github.com python projects` |
| `filetype:` | File type | `filetype:pdf annual report` |
| `inurl:` | URL contains | `inurl:login admin` |
| `intitle:` | Title contains | `intitle:"index of" mp3` |
| `intext:` | Body contains | `intext:password filetype:txt` |
| `cache:` | View cache | `cache:example.com` |
| `related:` | Related sites | `related:github.com` |
| `info:` | Site information | `info:example.com` |

### 1.3 Time filter parameters

| Parameter | Meaning | URL example |
|------|------|---------|
| `tbs=qdr:h` | Past hour | `https://www.google.com/search?q=news&tbs=qdr:h` |
| `tbs=qdr:d` | Past 24 hours | `https://www.google.com/search?q=news&tbs=qdr:d` |
| `tbs=qdr:w` | Past week | `https://www.google.com/search?q=news&tbs=qdr:w` |
| `tbs=qdr:m` | Past month | `https://www.google.com/search?q=news&tbs=qdr:m` |
| `tbs=qdr:y` | Past year | `https://www.google.com/search?q=news&tbs=qdr:y` |
| `tbs=cdr:1,cd_min:1/1/2024,cd_max:12/31/2024` | Custom date range | All of 2024 |

### 1.4 Language and region filters

| Parameter | Function | Example |
|------|------|------|
| `hl=en` | Interface language | `https://www.google.com/search?q=test&hl=en` |
| `lr=lang_zh-CN` | Result language | `https://www.google.com/search?q=test&lr=lang_zh-CN` |
| `cr=countryCN` | Country/region | `https://www.google.com/search?q=test&cr=countryCN` |
| `gl=us` | Geolocation | `https://www.google.com/search?q=test&gl=us` |

### 1.5 Special search types

| Type | URL | Notes |
|------|-----|------|
| Image search | `https://www.google.com/search?q={keyword}&tbm=isch` | `tbm=isch` means images |
| News search | `https://www.google.com/search?q={keyword}&tbm=nws` | `tbm=nws` means news |
| Video search | `https://www.google.com/search?q={keyword}&tbm=vid` | `tbm=vid` means videos |
| Maps search | `https://www.google.com/search?q={keyword}&tbm=map` | `tbm=map` means maps |
| Shopping search | `https://www.google.com/search?q={keyword}&tbm=shop` | `tbm=shop` means shopping |
| Books search | `https://www.google.com/search?q={keyword}&tbm=bks` | `tbm=bks` means books |
| Scholar search | `https://scholar.google.com/scholar?q={keyword}` | Google Scholar |

### 1.6 Google deep search examples

```javascript
// 1. Search GitHub for Python machine learning projects
web_fetch({"url": "https://www.google.com/search?q=site:github.com+python+machine+learning"})

// 2. Search for 2024 machine learning tutorials in PDF
web_fetch({"url": "https://www.google.com/search?q=machine+learning+tutorial+filetype:pdf&tbs=cdr:1,cd_min:1/1/2024"})

// 3. Search Python pages whose titles contain "tutorial"
web_fetch({"url": "https://www.google.com/search?q=intitle:tutorial+python"})

// 4. Search news from the past week
web_fetch({"url": "https://www.google.com/search?q=AI+breakthrough&tbs=qdr:w&tbm=nws"})

// 5. Search Chinese content (English interface, Chinese results)
web_fetch({"url": "https://www.google.com/search?q=人工智能&lr=lang_zh-CN&hl=en"})

// 6. Search laptops in a specific price range
web_fetch({"url": "https://www.google.com/search?q=laptop+%241000..%242000+best+rating"})

// 7. Search excluding Wikipedia results
web_fetch({"url": "https://www.google.com/search?q=python+programming+-wikipedia"})

// 8. Search academic literature
web_fetch({"url": "https://scholar.google.com/scholar?q=deep+learning+optimization"})

// 9. Search cached pages (view deleted content)
web_fetch({"url": "https://webcache.googleusercontent.com/search?q=cache:example.com"})

// 10. Search related sites
web_fetch({"url": "https://www.google.com/search?q=related:stackoverflow.com"})
```

---

## 🦆 DuckDuckGo Deep Search

### 2.1 DuckDuckGo feature highlights

| Feature | Syntax | Example |
|------|------|------|
| **Bangs shortcuts** | `!abbr` | `!g python` -> Google search |
| **Password generation** | `password` | `https://duckduckgo.com/?q=password+20` |
| **Color conversion** | `color` | `https://duckduckgo.com/?q=+%23FF5733` |
| **Link shortening** | `shorten` | `https://duckduckgo.com/?q=shorten+example.com` |
| **QR code generation** | `qr` | `https://duckduckgo.com/?q=qr+hello+world` |
| **UUID generation** | `uuid` | `https://duckduckgo.com/?q=uuid` |
| **Base64 encode/decode** | `base64` | `https://duckduckgo.com/?q=base64+hello` |

### 2.2 DuckDuckGo Bangs complete list

#### Search engines

| Bang | Target | Example |
|------|---------|------|
| `!g` | Google | `!g python tutorial` |
| `!b` | Bing | `!b weather` |
| `!y` | Yahoo | `!y finance` |
| `!sp` | Startpage | `!sp privacy` |
| `!brave` | Brave Search | `!brave tech` |

#### Programming and development

| Bang | Target | Example |
|------|---------|------|
| `!gh` | GitHub | `!gh tensorflow` |
| `!so` | Stack Overflow | `!so javascript error` |
| `!npm` | npmjs.com | `!npm express` |
| `!pypi` | PyPI | `!pypi requests` |
| `!mdn` | MDN Web Docs | `!mdn fetch api` |
| `!docs` | DevDocs | `!docs python` |
| `!docker` | Docker Hub | `!docker nginx` |

#### Knowledge and encyclopedias

| Bang | Target | Example |
|------|---------|------|
| `!w` | Wikipedia | `!w machine learning` |
| `!wen` | English Wikipedia | `!wen artificial intelligence` |
| `!wt` | Wiktionary | `!wt serendipity` |
| `!imdb` | IMDb | `!imdb inception` |

#### Shopping and prices

| Bang | Target | Example |
|------|---------|------|
| `!a` | Amazon | `!a wireless headphones` |
| `!e` | eBay | `!e vintage watch` |
| `!ali` | AliExpress | `!ali phone case` |

#### Maps and places

| Bang | Target | Example |
|------|---------|------|
| `!m` | Google Maps | `!m Beijing` |
| `!maps` | OpenStreetMap | `!maps Paris` |

### 2.3 DuckDuckGo search parameters

| Parameter | Function | Example |
|------|------|------|
| `kp=1` | Strict safe search | `https://duckduckgo.com/html/?q=test&kp=1` |
| `kp=-1` | Safe search off | `https://duckduckgo.com/html/?q=test&kp=-1` |
| `kl=cn` | China region | `https://duckduckgo.com/html/?q=news&kl=cn` |
| `kl=us-en` | US English | `https://duckduckgo.com/html/?q=news&kl=us-en` |
| `ia=web` | Web results | `https://duckduckgo.com/?q=test&ia=web` |
| `ia=images` | Image results | `https://duckduckgo.com/?q=test&ia=images` |
| `ia=news` | News results | `https://duckduckgo.com/?q=test&ia=news` |
| `ia=videos` | Video results | `https://duckduckgo.com/?q=test&ia=videos` |

### 2.4 DuckDuckGo deep search examples

```javascript
// 1. Use a Bang to jump to Google search
web_fetch({"url": "https://duckduckgo.com/html/?q=!g+machine+learning"})

// 2. Search GitHub projects directly
web_fetch({"url": "https://duckduckgo.com/html/?q=!gh+react"})

// 3. Find Stack Overflow answers
web_fetch({"url": "https://duckduckgo.com/html/?q=!so+python+list+comprehension"})

// 4. Generate a password
web_fetch({"url": "https://duckduckgo.com/?q=password+16"})

// 5. Base64 encode
web_fetch({"url": "https://duckduckgo.com/?q=base64+hello+world"})

// 6. Color code conversion
web_fetch({"url": "https://duckduckgo.com/?q=%23FF5733"})

// 7. Search YouTube videos
web_fetch({"url": "https://duckduckgo.com/html/?q=!yt+python+tutorial"})

// 8. View Wikipedia
web_fetch({"url": "https://duckduckgo.com/html/?q=!w+artificial+intelligence"})

// 9. Amazon product search
web_fetch({"url": "https://duckduckgo.com/html/?q=!a+laptop"})

// 10. Generate a QR code
web_fetch({"url": "https://duckduckgo.com/?q=qr+https://github.com"})
```

---

## 🔎 Brave Search Deep Search

### 3.1 Brave Search feature highlights

| Feature | Parameter | Example |
|------|------|------|
| **Independent index** | No Google/Bing dependency | Own crawler index |
| **Goggles** | Custom search rules | Create personal filters |
| **Discussions** | Forum discussion search | Aggregates Reddit and other forums |
| **News** | News aggregation | Independent news index |

### 3.2 Brave Search parameters

| Parameter | Function | Example |
|------|------|------|
| `tf=pw` | This week | `https://search.brave.com/search?q=news&tf=pw` |
| `tf=pm` | This month | `https://search.brave.com/search?q=tech&tf=pm` |
| `tf=py` | This year | `https://search.brave.com/search?q=AI&tf=py` |
| `safesearch=strict` | Strict safety | `https://search.brave.com/search?q=test&safesearch=strict` |
| `source=web` | Web search | Default |
| `source=news` | News search | `https://search.brave.com/search?q=tech&source=news` |
| `source=images` | Image search | `https://search.brave.com/search?q=cat&source=images` |
| `source=videos` | Video search | `https://search.brave.com/search?q=music&source=videos` |

### 3.3 Brave Search Goggles (custom filters)

Goggles let you create custom search rules:

```
$discard  // discard everything
$boost,site=stackoverflow.com  // boost Stack Overflow
$boost,site=github.com  // boost GitHub
$boost,site=docs.python.org  // boost Python docs
```

### 3.4 Brave Search deep search examples

```javascript
// 1. This week's tech news
web_fetch({"url": "https://search.brave.com/search?q=technology&tf=pw&source=news"})

// 2. This month's AI developments
web_fetch({"url": "https://search.brave.com/search?q=artificial+intelligence&tf=pm"})

// 3. Image search
web_fetch({"url": "https://search.brave.com/search?q=machine+learning&source=images"})

// 4. Video tutorials
web_fetch({"url": "https://search.brave.com/search?q=python+tutorial&source=videos"})

// 5. Search with the independent index
web_fetch({"url": "https://search.brave.com/search?q=privacy+tools"})
```

---

## 📊 WolframAlpha knowledge computation search

### 4.1 WolframAlpha data types

| Type | Query example | URL |
|------|---------|-----|
| **Math** | `integrate x^2 dx` | `https://www.wolframalpha.com/input?i=integrate+x%5E2+dx` |
| **Unit conversion** | `100 miles to km` | `https://www.wolframalpha.com/input?i=100+miles+to+km` |
| **Currency conversion** | `100 USD to CNY` | `https://www.wolframalpha.com/input?i=100+USD+to+CNY` |
| **Stock data** | `AAPL stock` | `https://www.wolframalpha.com/input?i=AAPL+stock` |
| **Weather** | `weather in Beijing` | `https://www.wolframalpha.com/input?i=weather+in+Beijing` |
| **Population data** | `population of China` | `https://www.wolframalpha.com/input?i=population+of+China` |
| **Chemical elements** | `properties of gold` | `https://www.wolframalpha.com/input?i=properties+of+gold` |
| **Nutrition** | `nutrition of apple` | `https://www.wolframalpha.com/input?i=nutrition+of+apple` |
| **Date arithmetic** | `days between Jan 1 2020 and Dec 31 2024` | Date interval computation |
| **Timezone conversion** | `10am Beijing to New York` | Timezone conversion |
| **IP addresses** | `8.8.8.8` | IP information lookup |
| **Barcodes** | `scan barcode 123456789` | Barcode information |
| **Flights** | `flight AA123` | Flight information |

### 4.2 WolframAlpha deep search examples

```javascript
// 1. Compute an integral
web_fetch({"url": "https://www.wolframalpha.com/input?i=integrate+sin%28x%29+from+0+to+pi"})

// 2. Solve an equation
web_fetch({"url": "https://www.wolframalpha.com/input?i=solve+x%5E2-5x%2B6%3D0"})

// 3. Live currency rate
web_fetch({"url": "https://www.wolframalpha.com/input?i=100+USD+to+CNY"})

// 4. Live stock data
web_fetch({"url": "https://www.wolframalpha.com/input?i=Apple+stock+price"})

// 5. City weather
web_fetch({"url": "https://www.wolframalpha.com/input?i=weather+in+Shanghai+tomorrow"})

// 6. Country statistics
web_fetch({"url": "https://www.wolframalpha.com/input?i=GDP+of+China+vs+USA"})

// 7. Chemistry computation
web_fetch({"url": "https://www.wolframalpha.com/input?i=molar+mass+of+H2SO4"})

// 8. Physical constants
web_fetch({"url": "https://www.wolframalpha.com/input?i=speed+of+light"})

// 9. Nutrition information
web_fetch({"url": "https://www.wolframalpha.com/input?i=calories+in+banana"})

// 10. Historical dates
web_fetch({"url": "https://www.wolframalpha.com/input?i=events+on+July+20+1969"})
```

---

## 🔧 Startpage privacy search

### 5.1 Startpage feature highlights

| Feature | Notes | URL |
|------|------|-----|
| **Proxy browsing** | Anonymously visit results | Click "Anonymous View" |
| **No tracking** | Search history not recorded | On by default |
| **EU servers** | Protected by EU privacy law | Data in Europe |
| **Image proxy** | Images loaded via proxy | Hides IP |

### 5.2 Startpage parameters

| Parameter | Function | Example |
|------|------|------|
| `cat=web` | Web search | Default |
| `cat=images` | Image search | `...&cat=images` |
| `cat=video` | Video search | `...&cat=video` |
| `cat=news` | News search | `...&cat=news` |
| `language=english` | English results | `...&language=english` |
| `time=day` | Past 24 hours | `...&time=day` |
| `time=week` | Past week | `...&time=week` |
| `time=month` | Past month | `...&time=month` |
| `time=year` | Past year | `...&time=year` |
| `nj=0` | Family filter off | `...&nj=0` |

### 5.3 Startpage deep search examples

```javascript
// 1. Privacy search
web_fetch({"url": "https://www.startpage.com/sp/search?query=privacy+tools"})

// 2. Privacy image search
web_fetch({"url": "https://www.startpage.com/sp/search?query=nature&cat=images"})

// 3. This week's news (privacy mode)
web_fetch({"url": "https://www.startpage.com/sp/search?query=tech+news&time=week&cat=news"})

// 4. English-results search
web_fetch({"url": "https://www.startpage.com/sp/search?query=machine+learning&language=english"})
```

---

## 🌍 Combined search strategy

### 6.1 Choosing an engine by search goal

| Search goal | Preferred engine | Alternatives | Reason |
|---------|---------|---------|------|
| **Academic research** | Google Scholar | Google, Brave | Academic resource indexing |
| **Programming** | Google | GitHub (DuckDuckGo bang) | Comprehensive technical docs |
| **Privacy-sensitive** | DuckDuckGo | Startpage, Brave | No user tracking |
| **Real-time news** | Brave News | Google News | Independent news index |
| **Knowledge computation** | WolframAlpha | Google | Structured data |
| **Chinese content** | Google HK | Bing | Good Chinese optimization |
| **European perspective** | Qwant | Startpage | EU compliance |
| **Eco-friendly** | Ecosia | DuckDuckGo | Plants trees per search |
| **Unfiltered** | Brave | Startpage | Unbiased results |

### 6.2 Multi-engine cross-validation

```javascript
// Strategy: search the same keyword across engines, compare results
const keyword = "climate change 2024";

// Get different perspectives
const searches = [
  { engine: "Google", url: `https://www.google.com/search?q=${keyword}&tbs=qdr:m` },
  { engine: "Brave", url: `https://search.brave.com/search?q=${keyword}&tf=pm` },
  { engine: "DuckDuckGo", url: `https://duckduckgo.com/html/?q=${keyword}` },
  { engine: "Ecosia", url: `https://www.ecosia.org/search?q=${keyword}` }
];

// Analyze the differences between engine results
```

### 6.3 Time-sensitive search strategy

| Timeliness need | Engine choice | Parameter settings |
|-----------|---------|---------|
| **Real-time (hourly)** | Google News, Brave News | `tbs=qdr:h`, `tf=pw` |
| **Recent (daily)** | Google, Brave | `tbs=qdr:d`, `time=day` |
| **This week** | All engines | `tbs=qdr:w`, `tf=pw` |
| **This month** | All engines | `tbs=qdr:m`, `tf=pm` |
| **Historical** | Google Scholar | Academic archives |

### 6.4 Domain-specific deep search

#### Technical development

```javascript
// GitHub project search
web_fetch({"url": "https://duckduckgo.com/html/?q=!gh+tensorflow+stars:%3E1000"})

// Stack Overflow questions
web_fetch({"url": "https://duckduckgo.com/html/?q=!so+python+memory+leak"})

// MDN docs
web_fetch({"url": "https://duckduckgo.com/html/?q=!mdn+javascript+async+await"})

// PyPI packages
web_fetch({"url": "https://duckduckgo.com/html/?q=!pypi+requests"})

// npm packages
web_fetch({"url": "https://duckduckgo.com/html/?q=!npm+express"})
```

#### Academic research

```javascript
// Google Scholar papers
web_fetch({"url": "https://scholar.google.com/scholar?q=deep+learning+2024"})

// Search PDF papers
web_fetch({"url": "https://www.google.com/search?q=machine+learning+filetype:pdf+2024"})

// arXiv papers
web_fetch({"url": "https://duckduckgo.com/html/?q=site:arxiv.org+quantum+computing"})
```

#### Finance and investment

```javascript
// Live stock data
web_fetch({"url": "https://www.wolframalpha.com/input?i=AAPL+stock"})

// Currency conversion
web_fetch({"url": "https://www.wolframalpha.com/input?i=EUR+to+USD"})

// Search earnings-report PDFs
web_fetch({"url": "https://www.google.com/search?q=Apple+Q4+2024+earnings+filetype:pdf"})
```

#### Current news

```javascript
// Google News
web_fetch({"url": "https://www.google.com/search?q=breaking+news&tbm=nws&tbs=qdr:h"})

// Brave News
web_fetch({"url": "https://search.brave.com/search?q=world+news&source=news"})

// DuckDuckGo News
web_fetch({"url": "https://duckduckgo.com/html/?q=tech+news&ia=news"})
```

---

## 🛠️ Advanced search technique summary

### URL encoding utility

```javascript
// URL-encode a keyword
function encodeKeyword(keyword) {
  return encodeURIComponent(keyword);
}

// Example
const keyword = "machine learning";
const encoded = encodeKeyword(keyword); // "machine%20learning"
```

### Batch search template

```javascript
// Multi-engine batch search function
function generateSearchUrls(keyword) {
  const encoded = encodeURIComponent(keyword);
  return {
    google: `https://www.google.com/search?q=${encoded}`,
    google_hk: `https://www.google.com.hk/search?q=${encoded}`,
    duckduckgo: `https://duckduckgo.com/html/?q=${encoded}`,
    brave: `https://search.brave.com/search?q=${encoded}`,
    startpage: `https://www.startpage.com/sp/search?query=${encoded}`,
    bing_intl: `https://cn.bing.com/search?q=${encoded}&ensearch=1`,
    yahoo: `https://search.yahoo.com/search?p=${encoded}`,
    ecosia: `https://www.ecosia.org/search?q=${encoded}`,
    qwant: `https://www.qwant.com/?q=${encoded}`
  };
}

// Usage example
const urls = generateSearchUrls("artificial intelligence");
```

### Time-filter helper

```javascript
// Google time-filter URL generator
function googleTimeSearch(keyword, period) {
  const periods = {
    hour: 'qdr:h',
    day: 'qdr:d',
    week: 'qdr:w',
    month: 'qdr:m',
    year: 'qdr:y'
  };
  return `https://www.google.com/search?q=${encodeURIComponent(keyword)}&tbs=${periods[period]}`;
}

// Usage example
const recentNews = googleTimeSearch("AI breakthrough", "week");
```

---

## 📝 Complete search example collection

```javascript
// ==================== Technical development ====================

// 1. Search GitHub for high-star Python projects
web_fetch({"url": "https://www.google.com/search?q=site:github.com+python+stars:%3E1000"})

// 2. Best Stack Overflow answers
web_fetch({"url": "https://duckduckgo.com/html/?q=!so+best+way+to+learn+python"})

// 3. MDN documentation lookup
web_fetch({"url": "https://duckduckgo.com/html/?q=!mdn+promises"})

// 4. Search npm packages
web_fetch({"url": "https://duckduckgo.com/html/?q=!npm+axios"})

// ==================== Academic research ====================

// 5. Google Scholar papers
web_fetch({"url": "https://scholar.google.com/scholar?q=transformer+architecture"})

// 6. Search PDF papers
web_fetch({"url": "https://www.google.com/search?q=attention+is+all+you+need+filetype:pdf"})

// 7. Latest arXiv papers
web_fetch({"url": "https://duckduckgo.com/html/?q=site:arxiv.org+abs+quantum"})

// ==================== Current news ====================

// 8. Latest Google News (past hour)
web_fetch({"url": "https://www.google.com/search?q=breaking+news&tbs=qdr:h&tbm=nws"})

// 9. This week's tech news on Brave
web_fetch({"url": "https://search.brave.com/search?q=technology&tf=pw&source=news"})

// 10. DuckDuckGo News
web_fetch({"url": "https://duckduckgo.com/html/?q=world+news&ia=news"})

// ==================== Finance and investment ====================

// 11. Live stock data
web_fetch({"url": "https://www.wolframalpha.com/input?i=Tesla+stock"})

// 12. Currency rate
web_fetch({"url": "https://www.wolframalpha.com/input?i=1+BTC+to+USD"})

// 13. Company earnings PDF
web_fetch({"url": "https://www.google.com/search?q=Microsoft+annual+report+2024+filetype:pdf"})

// ==================== Knowledge computation ====================

// 14. Math computation
web_fetch({"url": "https://www.wolframalpha.com/input?i=derivative+of+x%5E3+sin%28x%29"})

// 15. Unit conversion
web_fetch({"url": "https://www.wolframalpha.com/input?i=convert+100+miles+to+kilometers"})

// 16. Nutrition information
web_fetch({"url": "https://www.wolframalpha.com/input?i=protein+in+chicken+breast"})

// ==================== Privacy-protecting search ====================

// 17. DuckDuckGo privacy search
web_fetch({"url": "https://duckduckgo.com/html/?q=privacy+tools"})

// 18. Startpage anonymous search
web_fetch({"url": "https://www.startpage.com/sp/search?query=secure+messaging"})

// 19. Brave tracker-free search
web_fetch({"url": "https://search.brave.com/search?q=encryption+software"})

// ==================== Advanced combined search ====================

// 20. Google multi-condition exact search
web_fetch({"url": "https://www.google.com/search?q=%22machine+learning%22+site:github.com+filetype:pdf+2024"})

// 21. Search excluding specific sites
web_fetch({"url": "https://www.google.com/search?q=python+tutorial+-wikipedia+-w3schools"})

// 22. Price-range search
web_fetch({"url": "https://www.google.com/search?q=laptop+%24800..%241200+best+review"})

// 23. Quick jump with Bangs
web_fetch({"url": "https://duckduckgo.com/html/?q=!g+site:medium.com+python"})

// 24. Image search (Google)
web_fetch({"url": "https://www.google.com/search?q=beautiful+landscape&tbm=isch"})

// 25. Academic citation search
web_fetch({"url": "https://scholar.google.com/scholar?q=author:%22Geoffrey+Hinton%22"})
```

---

## 🔐 Privacy best practices

### Search engine privacy levels

| Engine | Tracking level | Data retention | Encryption | Recommended use |
|------|---------|---------|------|---------|
| **DuckDuckGo** | No tracking | None | Yes | Everyday private search |
| **Startpage** | No tracking | None | Yes | Google results with privacy |
| **Brave** | No tracking | None | Yes | Independent index, unbiased |
| **Qwant** | No tracking | None | Yes | EU compliance needs |
| **Google** | Heavy tracking | Long-term | Yes | Personalized results needed |
| **Bing** | Moderate tracking | Long-term | Yes | Microsoft service integration |

### Privacy search recommendations

1. **Everyday use**: DuckDuckGo or Brave
2. **Google results with privacy**: Startpage
3. **Academic research**: Google Scholar (less tracking for academic use)
4. **Sensitive queries**: Tor Browser + DuckDuckGo onion service
5. **Cross-device sync**: avoid signing into search-engine accounts

---

## 📚 References

- [Google search operators complete list](https://support.google.com/websearch/answer/...)
- [DuckDuckGo Bangs complete list](https://duckduckgo.com/bang)
- [Brave Search docs](https://search.brave.com/help/...)
- [WolframAlpha examples](https://www.wolframalpha.com/examples/)
