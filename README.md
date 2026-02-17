# El País Opinion Scraper – Selenium + BrowserStack

## Overview

This project implements a cross-browser automation workflow using **Selenium 4 (Python)** and **BrowserStack Automate**.

It performs the following:

- Navigates to **El País (Spanish edition)**.
- Scrapes the first five articles from the **Opinión** section.
- Extracts and prints:
  - Title (Spanish)
  - Full article content (Spanish)
  - Cover image (downloaded locally when available)
- Translates article titles to English using a **RapidAPI translation endpoint**.
- Identifies words repeated more than twice across translated titles.
- Executes locally and across **five parallel browser/device configurations on BrowserStack**.

The implementation is intentionally straightforward and readable, reflecting practical automation patterns suitable for a **Customer Engineer / Associate Automation role**.

---

## Setup & Execution

This section explains how to configure and run the project locally and on BrowserStack.

---

### 1. Prerequisites

- Python 3.9+
- Google Chrome (for local execution)
- A RapidAPI account (for translation API)
- A BrowserStack Automate account

---

### 2. Configure Environment Variables

Create a file named `.env` in the root directory of the project.

Add the following values:

```env
# RapidAPI Translation
RAPIDAPI_KEY=your_rapidapi_key_here
RAPIDAPI_HOST=google-translate113.p.rapidapi.com
TRANSLATE_API_URL=https://google-translate113.p.rapidapi.com/api/v1/translator/json

# BrowserStack Credentials
BROWSERSTACK_USERNAME=your_browserstack_username
BROWSERSTACK_ACCESS_KEY=your_browserstack_access_key
```

Where to get these:

- RapidAPI Key → RapidAPI Dashboard → Subscribed API → Security Tab
- BrowserStack Credentials → Automate Dashboard → Settings → Access Keys

Note: Do not commit `.env` to version control.

---

### 3. Install Dependencies

Create and activate a virtual environment:

#### macOS / Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

#### Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

Install required packages:

```bash
pip install -r requirements.txt
```

---

### 4. Run Locally

To verify functionality on your local machine:

```bash
python main.py --mode local
```

This will:
- Open El País
- Scrape five Opinion articles
- Print Spanish titles and content
- Download images into `outputs/images/`
- Translate titles
- Print repeated words analysis

---

### 5. Run on BrowserStack (Parallel Execution)

To execute across five parallel browser/device configurations:

```bash
python main.py --mode browserstack --parallel 5
```

You can monitor live sessions at:

BrowserStack → Automate Dashboard

---

### 6. Troubleshooting

If you encounter:

**403 Forbidden (RapidAPI)**  
→ Ensure the API key is correct and the API subscription is active.

**Invalid BrowserStack credentials**  
→ Verify username and access key in `.env`.

**WebDriver errors locally**  
→ Update Chrome and reinstall dependencies.

---


## Technical Highlights

### 1. W3C WebDriver (Selenium 4)

The project uses the W3C-compliant WebDriver standard:

- `webdriver.Remote()` for BrowserStack execution
- Explicit waits using [`WebDriverWait`](https://www.selenium.dev/documentation/webdriver/waits/)
- Element location via CSS selectors

Relevant references:
- W3C WebDriver Spec: https://www.w3.org/TR/webdriver/
- Selenium Python Docs: https://www.selenium.dev/documentation/webdriver/

---

### 2. Explicit Wait Strategy

Uses:

- [`WebDriverWait`](https://www.selenium.dev/documentation/webdriver/waits/#explicit-waits)
- [`expected_conditions`](https://www.selenium.dev/selenium/docs/api/py/webdriver_support/selenium.webdriver.support.expected_conditions.html)

This ensures:
- DOM readiness before extraction
- Reduced flakiness across remote browsers
- Stability across mobile and desktop environments

---

### 3. Parallel Execution (ThreadPoolExecutor)

Parallel execution across five BrowserStack sessions uses:

- [`concurrent.futures.ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html)

This allows:
- Concurrent remote sessions
- Cross-browser/device validation
- Simulation of real-world multi-session automation

---

### 4. Remote Execution via BrowserStack Automate

Sessions are created using:

- `bstack:options` capabilities (W3C standard)
- Device + OS combinations
- Desktop and real mobile browsers

Reference:
- BrowserStack Selenium Automate Docs:  
  https://www.browserstack.com/docs/automate/selenium/getting-started/python
- Capability Reference:  
  https://www.browserstack.com/docs/automate/selenium/select-browsers-and-devices

---

### 5. Translation API Integration

Uses:

- [`requests`](https://requests.readthedocs.io/en/latest/)
- RapidAPI Google Translate endpoint
- Secure key management using [`python-dotenv`](https://pypi.org/project/python-dotenv/)

This demonstrates:
- External API consumption
- Header-based authentication
- JSON payload handling
- Error handling for 400/403 responses

---

### 6. Image Extraction Strategy

Image extraction prioritizes:

- `meta[property="og:image"]`
- Fallback to `<article> figure img`

This ensures resilience across article layout variations.

---

### 7. Text Processing

Repeated word analysis uses:

- Regular expressions (`re`)
- Dictionary frequency counting
- Case normalization
- Simple filtering (`count > 2`)

This keeps the solution readable while fulfilling the assignment requirement.

---

## Non-Obvious Technologies & Libraries

These libraries are commonly used in professional automation workflows:

| Library | Purpose | Link |
|----------|----------|------|
| Selenium 4 | Browser automation framework | https://pypi.org/project/selenium/ |
| Requests | HTTP client for API calls | https://requests.readthedocs.io |
| python-dotenv | Environment variable management | https://pypi.org/project/python-dotenv/ |
| WebDriver Manager | Automatic driver management | https://pypi.org/project/webdriver-manager/ |
| BrowserStack Automate | Cloud cross-browser testing | https://www.browserstack.com/automate |

---

## Project Structure

```bash
/
├── main.py
├── requirements.txt
├── README.md
├── .env
├── outputs/
│   └── images/
└── venv/
```

### Directory Notes

- `main.py`  
  Core automation logic, scraping workflow, translation integration, and parallel execution.

- `outputs/images/`  
  Stores downloaded article cover images.

- `.env`  
  Contains API credentials (not committed).

- `venv/`  
  Python virtual environment for dependency isolation.

---

## Cross-Browser Coverage

The project executes against five configurations:

- Windows 11 – Chrome
- Windows 11 – Firefox
- macOS Ventura – Safari
- Samsung Galaxy (Android) – Chrome
- iPhone (iOS) – Safari

This demonstrates:

- Remote WebDriver usage
- Capability configuration
- Mobile + desktop parity validation

---

## Design Philosophy

The code prioritizes:

- Readability over abstraction
- Clear separation of concerns
- Explicit waits for stability
- Minimal hidden complexity
- Environment-based credential management

It is intentionally not over-engineered, making it easy to explain during technical discussions.

---

## Why This Matters for a Customer Engineer Role

This implementation demonstrates:

- Real-world Selenium experience
- Remote cloud execution
- Cross-browser troubleshooting awareness
- API integration skills
- Handling dynamic web content
- Debugging remote execution differences
- Writing automation that is explainable and maintainable

It reflects practical automation engineering aligned with BrowserStack’s ecosystem.

---
