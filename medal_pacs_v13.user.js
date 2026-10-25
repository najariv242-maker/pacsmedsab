// ==UserScript==
// @name         Medal PACS Multi-Hospital Cine Video, DICOM & Smart Search v13.1
// @namespace    local.pacs.ai
// @version      13.1.0
// @description  Debugged Stage 1+2: Fixed Auto-Login (doc/doc), Exact Dojo Search Binding (ctl09/ctl10/ctl16/bAllDates), Accurate Persian-to-Finglish Engine, Cross-Hospital Live Search + Untouched v12 Cine Video/DICOM/JPEG Engine
// @match        *://hh-pacs.medsab.ac.ir/*
// @match        *://vh-pacs.medsab.ac.ir/*
// @match        *://sbh-pacs.medsab.ac.ir/*
// @match        *://*.medsab.ac.ir/*
// @grant        GM_xmlhttpRequest
// @grant        GM_notification
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        unsafeWindow
// @connect      hh-pacs.medsab.ac.ir
// @connect      vh-pacs.medsab.ac.ir
// @connect      sbh-pacs.medsab.ac.ir
// @connect      medsab.ac.ir
// @connect      *
// @run-at       document-idle
// @allFrames    true
// ==/UserScript==

(function () {
    "use strict";

    // Avoid running inside tiny hidden iframes
    if (window.self !== window.top && (window.innerWidth < 200 || window.innerHeight < 200)) {
        return;
    }

    const HOSPITALS = [
        { code: "HH", name: "حشمتیه (HH)", host: "hh-pacs.medsab.ac.ir", origin: "https://hh-pacs.medsab.ac.ir", defaultPath: "/Medalwebpro" },
        { code: "VH", name: "واسطی (VH)", host: "vh-pacs.medsab.ac.ir", origin: "https://vh-pacs.medsab.ac.ir", defaultPath: "/Medalwebpro" },
        { code: "SBH", name: "شهید بهشتی (SBH)", host: "sbh-pacs.medsab.ac.ir", origin: "https://sbh-pacs.medsab.ac.ir", defaultPath: "/MedalWeb" }
    ];

    const DEFAULT_CREDENTIALS = {
        username: "doc",
        password: "doc"
    };

    const pagePath = window.location.pathname.toLowerCase();
    const isLoginPage = pagePath.includes("login");
    const isSearchPage = pagePath.includes("default") || pagePath.includes("search");
    const isViewerPage = pagePath.includes("process") || pagePath.includes("viewer");
    const isMedalPage = isLoginPage || isSearchPage || isViewerPage || pagePath.includes("medal");

    if (!isMedalPage) {
        const win = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
        if (!win.Studies && !win.Series) return;
    }

    let isRunning = false;
    let stopRequested = false;

    const state = {
        studyKey: null,
        patientName: "Patient",
        patientID: "",
        modality: "CT",
        seriesList: [],
        selectedSeriesKey: null,
        outputFormat: "VIDEO", // "VIDEO", "DICOM", or "JPEG"
        fps: 20, // Customizable FPS: 5, 10, 15, 20, 25, 30, 60
        playMode: "PINGPONG", // "FORWARD" or "PINGPONG" (1->N->1 like Rec 0016.mp4)
        includeOverlay: true, // Medical HUD annotations like Rec 0016.mp4
        repeatCount: 1, // Repeat loops for video
        activeSeriesNdx: 0,
        ww: null,
        wc: null,
        // v13.1 Smart Search & Auto-Login state:
        autoLoginEnabled: localStorage.getItem("pacs_v13_autologin") !== "0",
        activeTab: isViewerPage ? "DOWNLOAD" : "SEARCH",
        searchQueryPersian: sessionStorage.getItem("pacs_v13_last_q") || "",
        searchPid: sessionStorage.getItem("pacs_v13_last_pid") || "",
        searchNid: sessionStorage.getItem("pacs_v13_last_nid") || "",
        searchModality: sessionStorage.getItem("pacs_v13_last_mod") || "ALL",
        searchDatePreset: sessionStorage.getItem("pacs_v13_last_date") || "ALL",
        generatedVariants: [],
        selectedRowOnDefault: null
    };

    const ui = {
        panel: null,
        seriesSelect: null,
        formatSelect: null,
        videoOptionsBox: null,
        fpsInput: null,
        fpsValDisplay: null,
        modeSelect: null,
        overlayCheckbox: null,
        metaBox: null,
        startBtn: null,
        stopBtn: null,
        progressBar: null,
        percentText: null,
        statusText: null,
        logBox: null,
        // v13.1 UI references
        tabBtnDownload: null,
        tabBtnSearch: null,
        tabContentDownload: null,
        tabContentSearch: null,
        openViewerBtn: null,
        persianInput: null,
        variantsBox: null,
        pidInput: null,
        nidInput: null,
        modalitySelect: null,
        datePresetSelect: null,
        multiResultsBox: null,
        autoLoginCheckbox: null
    };

    function now() { return new Date().toLocaleTimeString(); }
    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    function log(message, type = "info") {
        if (!ui.logBox) return;
        const line = document.createElement("div");
        line.textContent = `[${now()}] ${message}`;
        line.style.color =
            type === "error" ? "#ff6b6b" :
            type === "success" ? "#4ade80" :
            type === "warning" ? "#fbbf24" :
            "#94a3b8";
        ui.logBox.appendChild(line);
        ui.logBox.scrollTop = ui.logBox.scrollHeight;
    }

    function setStatus(message, type = "info") {
        if (!ui.statusText) return;
        ui.statusText.textContent = message;
        ui.statusText.style.color =
            type === "error" ? "#ff6b6b" :
            type === "success" ? "#4ade80" :
            type === "warning" ? "#38bdf8" :
            "#94a3b8";
    }

    function isInsideOurPanel(el) {
        return Boolean(el && el.closest && (el.closest("#pacs-v13-panel") || el.closest("#pacs-v12-panel")));
    }

    // =========================================================================
    // MODULE A: Fixed Auto-Login (doc/doc) & Direct Telegram Deep-Link Handler
    // =========================================================================
    function checkAndPerformAutoLogin() {
        const urlParams = new URLSearchParams(window.location.search);
        const tgSk = urlParams.get("tg_sk");
        if (tgSk) sessionStorage.setItem("pacs_v13_pending_sk", tgSk);

        const tgPid = urlParams.get("tg_pid");
        if (tgPid) sessionStorage.setItem("pacs_v13_pending_pid", tgPid);

        const tgName = urlParams.get("tg_name");
        if (tgName) sessionStorage.setItem("pacs_v13_pending_name", tgName);

        const tgAutoView = urlParams.get("tg_autoview");
        if (tgAutoView) sessionStorage.setItem("pacs_v13_pending_autoview", tgAutoView);

        const tgAutoDl = urlParams.get("tg_autodl");
        if (tgAutoDl) sessionStorage.setItem("pacs_v13_pending_autodl", tgAutoDl);

        if (isLoginPage) {
            if (!state.autoLoginEnabled) {
                log("لاگین خودکار غیرفعال است.", "warning");
                return;
            }
            const lastAttempt = parseInt(sessionStorage.getItem("pacs_v13_login_ts") || "0", 10);
            if (Date.now() - lastAttempt < 3500) {
                log("در انتظار پاسخ سرور برای لاگین...", "warning");
                return;
            }

            let attempts = 0;
            const loginTimer = setInterval(() => {
                attempts++;
                if (attempts > 15) {
                    clearInterval(loginTimer);
                    return;
                }

                // Strictly exclude our own panel elements!
                const passInputs = Array.from(document.querySelectorAll('input[type="password"]')).filter(el => !isInsideOurPanel(el));
                const passInput = passInputs[0];
                if (!passInput) return;

                const textInputs = Array.from(document.querySelectorAll('input[type="text"], input:not([type])'))
                    .filter(el => !isInsideOurPanel(el) && el.type !== "hidden" && el.type !== "password" && !el.readOnly && !el.disabled);
                const userInput = textInputs[0];
                if (!userInput) return;

                // Find the page's actual LOGIN button (never inside #pacs-v13-panel!)
                const candidates = Array.from(document.querySelectorAll(
                    'input[type="submit"], input[type="image"], input[type="button"], button, a'
                )).filter(el => !isInsideOurPanel(el));

                const loginBtn = candidates.find(el => {
                    const txt = ((el.value || el.textContent || el.id || el.name || "") + "").toLowerCase();
                    return txt.includes("login") || txt.includes("ورود") || txt.includes("blogin") || txt.includes("btnlogin") || el.type === "submit";
                }) || candidates[0];

                clearInterval(loginTimer);

                // Set values natively so ASP.NET / Dojo / browser autofill all register them
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
                if (nativeInputValueSetter) {
                    nativeInputValueSetter.call(userInput, DEFAULT_CREDENTIALS.username);
                    nativeInputValueSetter.call(passInput, DEFAULT_CREDENTIALS.password);
                } else {
                    userInput.value = DEFAULT_CREDENTIALS.username;
                    passInput.value = DEFAULT_CREDENTIALS.password;
                }

                userInput.dispatchEvent(new Event("input", { bubbles: true }));
                userInput.dispatchEvent(new Event("change", { bubbles: true }));
                passInput.dispatchEvent(new Event("input", { bubbles: true }));
                passInput.dispatchEvent(new Event("change", { bubbles: true }));

                sessionStorage.setItem("pacs_v13_login_ts", String(Date.now()));
                log("در حال ورود خودکار با نام کاربری doc ...", "warning");
                setStatus("ورود خودکار (doc/doc)...", "warning");

                setTimeout(() => {
                    if (loginBtn) {
                        loginBtn.click();
                    } else if (passInput.form) {
                        passInput.form.submit();
                    }
                }, 200);
            }, 300);
            return;
        }

        // 1. Direct jump to Process.aspx?SK=... if requested by Telegram link
        const pendingSk = sessionStorage.getItem("pacs_v13_pending_sk");
        if (pendingSk && !isViewerPage) {
            sessionStorage.removeItem("pacs_v13_pending_sk");
            const base = getAppBasePath() || "/Medalwebpro";
            window.location.href = `${window.location.origin}${base}/Process.aspx?SK=${encodeURIComponent(pendingSk)}`;
            return;
        }

        // 2. If Telegram link passed ?tg_pid=... or ?tg_name=... to Default.aspx:
        if (isSearchPage) {
            const pendingPid = sessionStorage.getItem("pacs_v13_pending_pid");
            const pendingName = sessionStorage.getItem("pacs_v13_pending_name");
            const pendingAutoView = sessionStorage.getItem("pacs_v13_pending_autoview");

            if (pendingPid || pendingName) {
                sessionStorage.removeItem("pacs_v13_pending_pid");
                sessionStorage.removeItem("pacs_v13_pending_name");
                setTimeout(() => {
                    if (pendingPid && ui.pidInput) {
                        ui.pidInput.value = pendingPid;
                        state.searchPid = pendingPid;
                    }
                    if (pendingName && ui.persianInput) {
                        ui.persianInput.value = pendingName;
                        state.searchQueryPersian = pendingName;
                        renderVariantChips(pendingName);
                    }
                    state.searchDatePreset = "ALL";
                    if (ui.datePresetSelect) ui.datePresetSelect.value = "ALL";
                    const { primary } = generateSearchVariants(pendingName || "");
                    applySearchInCurrentPage(primary);
                }, 600);
                return;
            }

            // If returning from search postback and tg_autoview=1 was set, auto-open first matching row!
            if (pendingAutoView === "1") {
                sessionStorage.removeItem("pacs_v13_pending_autoview");
                setTimeout(() => {
                    const rows = getPatientRowsOnDefaultPage();
                    if (rows.length > 0) {
                        log("بیمار یافت شد! در حال باز کردن خودکار ویوئر...", "success");
                        rows[0].tr.click();
                        setTimeout(() => triggerDefaultPageView(), 300);
                    }
                }, 700);
            }
        }

        // 3. If on Process.aspx and Telegram requested auto-download
        const pendingAutoDl = sessionStorage.getItem("pacs_v13_pending_autodl");
        if (pendingAutoDl && isViewerPage) {
            sessionStorage.removeItem("pacs_v13_pending_autodl");
            if (["VIDEO", "DICOM", "JPEG"].includes(pendingAutoDl.toUpperCase())) {
                state.outputFormat = pendingAutoDl.toUpperCase();
                setTimeout(() => {
                    refreshUIState();
                    if (state.studyKey && state.seriesList.length > 0) {
                        startDownload();
                    }
                }, 1500);
            }
        }
    }

    // =========================================================================
    // MODULE B: Linguistically Accurate Persian-to-Finglish Phonetic Engine
    // =========================================================================
    const WORD_DICTIONARY = {
        "علی": ["ALI"],
        "علیرضا": ["ALIREZA", "ALI REZA"],
        "محمد": ["MOHAMMAD", "MOHAMAD", "MOHMMAD"],
        "محمدرضا": ["MOHAMMADREZA", "MOHAMADREZA", "MOHAMMAD REZA", "MOHAMAD REZA"],
        "حسین": ["HOSSEIN", "HOSEIN", "HOSIEN", "HOSEYI"],
        "حسن": ["HASAN", "HASSAN"],
        "فاطمه": ["FATEME", "FATEMEH", "FATMA"],
        "زهرا": ["ZAHRA"],
        "مهدی": ["MAHDI", "MEHDI"],
        "مهدیه": ["MAHDIYE", "MAHDIYEH", "MAHDIEH", "MEHDIYEH"],
        "امیر": ["AMIR"],
        "امیرحسین": ["AMIRHOSSEIN", "AMIRHOSEIN", "AMIR HOSSEIN", "AMIR HOSEIN"],
        "امیرمحمد": ["AMIRMOHAMMAD", "AMIR MOHAMMAD", "AMIR MOHAMAD"],
        "ابوالفضل": ["ABOLFAZL", "ABOLFAZEL"],
        "مرضیه": ["MARZIYEH", "MARZIEH", "MARZIYE", "MARZIE"],
        "طاهره": ["TAHERE", "TAHEREH"],
        "طیبه": ["TAYEBE", "TAYEBEH", "TAIEBE"],
        "بهجت": ["BEHJAT"],
        "نرگس": ["NARGES", "NARGESS"],
        "منیره": ["MONIRE", "MONIREH"],
        "ناهید": ["NAHID"],
        "راستگو": ["RASTGOO", "RASTGO", "RASTGOU", "RASTGU", "RAST"],
        "فاضلی": ["FAZELI", "FAZELY", "FAZLI", "FAZEL"],
        "فاضل": ["FAZEL"],
        "راد": ["RAD"],
        "حسینی": ["HOSEINI", "HOSSEINI", "HOSINI", "HOSEYNI"],
        "میرحسینی": ["MIR HOSEINI", "MIRHOSEINI", "MIR HOSSEINI", "MIRHOSSEINI"],
        "میر": ["MIR"],
        "صانع": ["SANE", "SANEE", "SANEI"],
        "سدیدی": ["SADIDI", "SADIDY"],
        "مکارم": ["MAKAREM"],
        "خیرآبادی": ["KHEIRABADI", "KHEYRABADI", "KHIRABADI"],
        "دلاور": ["DELAVAR", "DELAWAR"],
        "دلاوری": ["DELAVARI", "DELAVARY", "DELAVAR"],
        "توفیقیان": ["TOFIGHIAN", "TOFIQIAN", "TOFIGHYAN"],
        "شاهرینی": ["SHAHRAYNI", "SHAHREINI", "SHAHRINI", "SHAHRAINI"],
        "صفری": ["SAFARI", "SAFARY"],
        "دهقان": ["DEHGHAN", "DEHQAN"],
        "دهقانی": ["DEHGHANI", "DEHQANI", "DEHGHANY"],
        "غفوری": ["GHAFORI", "GHAFOURI", "GHAFOORI", "QAFOURI"],
        "چوپان": ["CHOPAN", "CHOOPAN", "CHOUPAN"],
        "شهرآبادی": ["SHAHRABADI", "SHAHR ABADI"],
        "داوچی": ["DAVACHI", "DAVACHY"],
        "برغمدی": ["BARGHAMADI", "BARGHAMADY"],
        "احمدآبادی": ["AHMADABADI", "AHMAD ABADI"],
        "باباکلانی": ["BABAKALANI", "BABA KALANI"],
        "کمایستانی": ["KAMAYESTANI", "KAMAESTANI"],
        "حیدری": ["HEIDARI", "HEYDARI", "HIDARI", "HEIDARY"],
        "مقصودی": ["MAGHSOODI", "MAGHSODI", "MAGHSOUDI", "MAQSOODI"],
        "براتی": ["BARATI", "BARATY"],
        "شاملو": ["SHAMLOO", "SHAMLU", "SHAMLOU", "SHAMLO"],
        "رضایی": ["REZAEI", "REZAI", "REZAEE", "REZAYI"],
        "محمدی": ["MOHAMMADI", "MOHAMADI", "MOHAMMADY"],
        "احمدی": ["AHMADI", "AHMADY"],
        "کریمی": ["KARIMI", "KARIMY"],
        "رحیمی": ["RAHIMI", "RAHIMY"],
        "جعفری": ["JAFARI", "JAFARY", "JAAFARI"],
        "موسوی": ["MOUSAVI", "MOSAVI", "MOOSAVI", "MUSAVI"],
        "هاشمی": ["HASHEMI", "HASHEMY"],
        "قاسمی": ["GHASEMI", "QASEMI", "GHASSEMI"]
    };

    // Common Persian stems/morphemes so compound names split cleanly without extra vowels
    const MORPHEME_RULES = [
        [/^راست/g, ["RAST"]],
        [/^تخت/g, ["TAKHT"]],
        [/^بخت/g, ["BAKHT"]],
        [/^سخت/g, ["SAKHT"]],
        [/^دوست/g, ["DOOST", "DOST", "DOUST"]],
        [/^پوست/g, ["POOST", "POST"]],
        [/^امیر/g, ["AMIR"]],
        [/^محمد/g, ["MOHAMMAD", "MOHAMAD"]],
        [/^علی/g, ["ALI"]],
        [/^حسین/g, ["HOSSEIN", "HOSEIN"]],
        [/^حسن/g, ["HASAN", "HASSAN"]],
        [/^غلام/g, ["GHOLAM", "QOLAM"]],
        [/^عبدال/g, ["ABDOL"]],
        [/^ابوال/g, ["ABOL"]],
        [/^سید/g, ["SEYED", "SEYYED", "SAIED"]],
        [/^میر/g, ["MIR"]],
        [/^شاه/g, ["SHAH"]],
        [/^شهر/g, ["SHAHR"]],
        [/^مهر/g, ["MEHR"]],
        [/^بهار/g, ["BAHAR"]],
        [/^خیر/g, ["KHEIR", "KHEYR", "KHIR"]],
        [/^نور/g, ["NOOR", "NOUR", "NOR"]],
        [/^پور$/g, ["POUR", "POOR", "PUR"]],
        [/^لو$/g, ["LOO", "LOU", "LU", "LO"]],
        [/^گو$/g, ["GOO", "GO", "GOU", "GU"]],
        [/^جو$/g, ["JOO", "JOU", "JO"]],
        [/^رو$/g, ["ROO", "RO", "ROU"]],
        [/^نژاد$/g, ["NEZHAD", "NEJAD"]],
        [/^زاده$/g, ["ZADEH", "ZADE"]],
        [/^فر$/g, ["FAR"]],
        [/^منش$/g, ["MANESH"]],
        [/^تبار$/g, ["TABAR"]],
        [/^وند$/g, ["VAND"]],
        [/^نیا$/g, ["NIA", "NIYA"]],
        [/^یان$/g, ["IAN", "YAN"]],
        [/^آباد$/g, ["ABAD"]],
        [/^آبادی$/g, ["ABADI", "ABADY"]],
        [/^ابادی$/g, ["ABADI", "ABADY"]],
        [/^ستانی$/g, ["ESTANI", "STANI"]]
    ];

    const CHAR_MAP = {
        "آ": "A", "ا": "A", "ب": "B", "پ": "P", "ت": "T", "ث": "S",
        "ج": "J", "چ": "CH", "ح": "H", "خ": "KH", "د": "D", "ذ": "Z",
        "ر": "R", "ز": "Z", "ژ": "ZH", "س": "S", "ش": "SH", "ص": "S",
        "ض": "Z", "ط": "T", "ظ": "Z", "ع": "A", "غ": "GH",
        "ف": "F", "ق": "GH", "ک": "K", "ك": "K", "گ": "G", "ل": "L",
        "م": "M", "ن": "N", "و": "O", "ه": "H", "ی": "I", "ي": "I", "ئ": "E"
    };

    function transliterateSinglePersianWord(word) {
        const clean = word.trim().replace(/\u200c/g, "");
        if (!clean) return [];
        if (WORD_DICTIONARY[clean]) return WORD_DICTIONARY[clean];

        // Check if word is a known prefix + suffix combination (e.g., راست + گو)
        let prefixAlts = [""];
        let suffixAlts = [""];
        let core = clean;

        for (const [regex, replacements] of MORPHEME_RULES) {
            const src = regex.source;
            if (src.startsWith("^") && regex.test(core)) {
                const matched = core.match(regex)[0];
                if (matched.length < core.length) {
                    prefixAlts = replacements;
                    core = core.slice(matched.length);
                    break;
                }
            }
        }

        for (const [regex, replacements] of MORPHEME_RULES) {
            const src = regex.source;
            if (src.endsWith("$") && regex.test(core)) {
                const matched = core.match(regex)[0];
                if (matched.length <= core.length) {
                    suffixAlts = replacements;
                    core = core.slice(0, core.length - matched.length);
                    break;
                }
            }
        }

        const coreVariants = new Set();
        if (!core) {
            coreVariants.add("");
        } else if (WORD_DICTIONARY[core]) {
            WORD_DICTIONARY[core].forEach(v => coreVariants.add(v));
        } else {
            const longVowels = ["ا", "آ", "و", "ی", "ي"];
            for (const vowelMode of [0, 1, 2]) {
                let out = "";
                for (let i = 0; i < core.length; i++) {
                    const ch = core[i];
                    const prevCh = i > 0 ? core[i - 1] : "";
                    const nextCh = core[i + 1] || "";
                    const isLast = i === core.length - 1;

                    if (i === 0 && (ch === "ا" || ch === "آ")) {
                        out += (vowelMode === 1 ? "E" : "A");
                        continue;
                    }
                    if (isLast && ch === "ه") {
                        out += (vowelMode === 0 ? "E" : "EH");
                        continue;
                    }
                    if (isLast && (ch === "ی" || ch === "ي")) {
                        out += (vowelMode === 2 ? "Y" : "I");
                        continue;
                    }
                    if (isLast && ch === "و") {
                        out += (vowelMode === 0 ? "OO" : vowelMode === 1 ? "O" : "OU");
                        continue;
                    }
                    if (ch === "و") {
                        if (i === 0) out += "V";
                        else out += (vowelMode === 0 ? "O" : vowelMode === 1 ? "OO" : "V");
                        continue;
                    }
                    if (ch === "ی" || ch === "ي") {
                        if (i === 0) out += "Y";
                        else out += (vowelMode === 0 ? "I" : vowelMode === 1 ? "EI" : "EY");
                        continue;
                    }
                    if (ch === "ق" || ch === "غ") {
                        out += (vowelMode === 2 ? "Q" : "GH");
                        continue;
                    }

                    out += (CHAR_MAP[ch] !== undefined ? CHAR_MAP[ch] : ch);

                    // Insert short vowel ONLY when needed:
                    // Never insert a vowel right after a syllable that just had a long vowel + consonant cluster (like راست -> R+A+S+T)
                    const isCurrConsonant = !longVowels.includes(ch) && ch !== "ه";
                    const isNextConsonant = nextCh && !longVowels.includes(nextCh);
                    const prevWasLongVowel = longVowels.includes(prevCh);

                    if (!isLast && isCurrConsonant && isNextConsonant) {
                        // If previous char was a long vowel (like 'ا' in راست), 'س' closes the syllable (RAS-T), so NO vowel after 'س'!
                        if (prevWasLongVowel) {
                            continue;
                        }
                        if (i === 0) {
                            out += (vowelMode === 1 ? "E" : "A");
                        } else if (vowelMode === 0) {
                            out += "A";
                        } else if (vowelMode === 1) {
                            out += "E";
                        }
                    }
                }
                coreVariants.add(out.toUpperCase());
            }
        }

        const results = new Set();
        for (const p of prefixAlts) {
            for (const c of coreVariants) {
                for (const s of suffixAlts) {
                    const combined = (p + c + s).replace(/([A-Z])\1{2,}/g, "$1$1");
                    if (combined) results.add(combined);
                }
            }
        }

        const baseArr = Array.from(results);
        for (const item of baseArr) {
            if (item.endsWith("I")) results.add(item.slice(0, -1) + "Y");
            if (item.endsWith("E")) results.add(item + "H");
            if (item.endsWith("OO")) {
                results.add(item.slice(0, -1)); // RASTGOO -> RASTGO
                results.add(item.slice(0, -2) + "OU"); // RASTGOU
            }
        }

        // Also add 4-5 char root stem at the end for broad PACS partial search
        if (baseArr[0] && baseArr[0].length >= 5) {
            results.add(baseArr[0].slice(0, 4));
        }

        return Array.from(results).filter(Boolean);
    }

    function generateSearchVariants(inputStr) {
        const raw = (inputStr || "").trim();
        if (!raw) return { primary: "", variants: [], tokens: [] };

        if (/^[a-zA-Z\s\^\-]+$/.test(raw)) {
            const upper = raw.toUpperCase().trim();
            const parts = upper.split(/[\s\^]+/).filter(Boolean);
            const variants = new Set([upper]);
            if (parts.length >= 2) {
                const first = parts[0];
                const last = parts.slice(1).join(" ");
                variants.add(last);
                variants.add(`${last} ${first}`);
                variants.add(`${last}^${first}`);
                for (const p of parts) {
                    if (p.length >= 3) variants.add(p);
                    if (p.endsWith("I")) variants.add(p.slice(0, -1) + "Y");
                    if (p.endsWith("Y")) variants.add(p.slice(0, -1) + "I");
                }
            } else if (parts.length === 1 && parts[0].length >= 4) {
                const w = parts[0];
                if (w.endsWith("I")) variants.add(w.slice(0, -1) + "Y");
                if (w.endsWith("Y")) variants.add(w.slice(0, -1) + "I");
                if (w.endsWith("OO")) variants.add(w.slice(0, -1));
                if (w.endsWith("O")) variants.add(w + "O");
                variants.add(w.slice(0, 4));
            }
            const list = Array.from(variants);
            return { primary: list[0], variants: list, tokens: parts };
        }

        const words = raw.split(/\s+/).filter(Boolean);
        const wordVariants = words.map(w => transliterateSinglePersianWord(w));
        const allVariants = new Set();

        if (words.length === 1) {
            wordVariants[0].forEach(v => allVariants.add(v));
        } else {
            const firstVars = wordVariants[0];
            const secondVars = wordVariants[1] || [];
            const lastVars = wordVariants[wordVariants.length - 1] || [];

            // Put Surname variants first because PACS sorts/starts with Surname!
            secondVars.forEach(v => { if (v.length >= 3) allVariants.add(v); });
            if (words.length > 2) {
                const mid = secondVars[0] || "";
                const tail = lastVars[0] || "";
                if (mid && tail) {
                    allVariants.add(`${mid} ${tail}`);
                    allVariants.add(`${mid}${tail}`);
                }
                lastVars.forEach(v => { if (v.length >= 3) allVariants.add(v); });
            }

            // Combined Surname + GivenName formats (both space and ^)
            if (words.length === 2 && secondVars[0] && firstVars[0]) {
                allVariants.add(`${secondVars[0]} ${firstVars[0]}`);
                allVariants.add(`${secondVars[0]}^${firstVars[0]}`);
            } else if (words.length >= 3 && secondVars[0] && lastVars[0] && firstVars[0]) {
                allVariants.add(`${secondVars[0]} ${lastVars[0]} ${firstVars[0]}`);
                allVariants.add(`${secondVars[0]} ${lastVars[0]}^${firstVars[0]}`);
            }

            firstVars.forEach(v => { if (v.length >= 3) allVariants.add(v); });
        }

        const list = Array.from(allVariants).filter(Boolean);
        return {
            primary: list[0] || "",
            variants: list.slice(0, 14),
            tokens: wordVariants
        };
    }

    // =========================================================================
    // MODULE C: Exact Dojo/ASP.NET Control Binding on Default.aspx (Verified from JSON)
    // =========================================================================
    function setDojoOrNativeInput(selectorOrEl, value) {
        const el = typeof selectorOrEl === "string" ? document.querySelector(selectorOrEl) : selectorOrEl;
        if (!el) return false;

        const win = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
        try {
            if (win.dijit && typeof win.dijit.byId === "function" && el.id) {
                const widget = win.dijit.byId(el.id);
                if (widget && typeof widget.set === "function") {
                    widget.set("value", value);
                }
            }
        } catch (e) {}

        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
        if (nativeSetter) {
            nativeSetter.call(el, value);
        } else {
            el.value = value;
        }

        // Hide Dojo placeholder span if value is non-empty
        if (el.parentElement) {
            const ph = el.parentElement.querySelector(".dijitPlaceHolder");
            if (ph) ph.style.display = value ? "none" : "";
        }

        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
        return true;
    }

    function findSearchFormControls() {
        return {
            // Verified exact IDs and names from medal_pacs_bot_schema_sbh-pacs.json:
            patientName: document.querySelector('#dijit_form_TextBox_0, input[name="ctl09"]'),
            nationalId: document.querySelector('#dijit_form_TextBox_1, input[name="ctl10"]'),
            modality: document.querySelector('#dojox_form_CheckedMultiSelect_0, select[name="ctl11"]'),
            startDateCb: document.querySelector('#ctl12_cb, input[name="ctl12$cb"]'),
            startDateText: document.querySelector('#ctl12_DT'),
            startDateHidden: document.querySelector('input[name="ctl12$DT"]'),
            bodyPart: document.querySelector('#dijit_form_TextBox_2, input[name="ctl14"]'),
            xId: document.querySelector('#dijit_form_TextBox_3, input[name="ctl15"]'),
            patientId: document.querySelector('#dijit_form_TextBox_4, input[name="ctl16"]'),
            endDateCb: document.querySelector('#ctl18_cb, input[name="ctl18$cb"]'),
            endDateText: document.querySelector('#ctl18_DT'),
            endDateHidden: document.querySelector('input[name="ctl18$DT"]'),
            refPhysician: document.querySelector('#dijit_form_TextBox_5, input[name="ctl20"]'),
            // Top toolbar action buttons:
            searchBtn: document.querySelector('#bSearch_imgMain, input[name="bSearch$imgMain"]'),
            allDatesBtn: document.querySelector('#bAllDates_imgMain, input[name="bAllDates$imgMain"]'),
            todayBtn: document.querySelector('#bToday_imgMain, input[name="bToday$imgMain"]'),
            yesterdayBtn: document.querySelector('#bYesterday_imgMain, input[name="bYesterday$imgMain"]'),
            lastWeekBtn: document.querySelector('#bLastWeek_imgMain, input[name="bLastWeek$imgMain"]'),
            resetBtn: document.querySelector('#bReset_imgMain, input[name="bReset$imgMain"]'),
            viewBtn: document.querySelector('#bView_imgMain, [onclick*="OnView"]')
        };
    }

    function applySearchInCurrentPage(queryVariant) {
        const controls = findSearchFormControls();
        if (!controls.patientName && !controls.searchBtn) {
            log("ابتدا وارد صفحه لیست بیماران (Default.aspx) شوید.", "error");
            return;
        }

        // Save search state across ASP.NET full page postback!
        sessionStorage.setItem("pacs_v13_last_q", state.searchQueryPersian || "");
        sessionStorage.setItem("pacs_v13_last_pid", state.searchPid || "");
        sessionStorage.setItem("pacs_v13_last_nid", state.searchNid || "");
        sessionStorage.setItem("pacs_v13_last_mod", state.searchModality || "ALL");
        sessionStorage.setItem("pacs_v13_last_date", state.searchDatePreset || "ALL");

        const targetName = (queryVariant !== undefined ? queryVariant : "").trim();
        setDojoOrNativeInput(controls.patientName, targetName);
        setDojoOrNativeInput(controls.patientId, (state.searchPid || "").trim());
        setDojoOrNativeInput(controls.nationalId, (state.searchNid || "").trim());

        if (controls.modality && state.searchModality) {
            const modVal = state.searchModality === "ALL" ? "" : state.searchModality;
            Array.from(controls.modality.options || []).forEach(opt => {
                opt.selected = Boolean(modVal && opt.value.toUpperCase() === modVal);
            });
            controls.modality.dispatchEvent(new Event("change", { bubbles: true }));
        }

        // Crucial fix: When searching for a person's name/ID and date preset is ALL,
        // click #bAllDates_imgMain (or uncheck Start/End date checkboxes) so it doesn't only search today!
        if (state.searchDatePreset === "ALL") {
            if (controls.startDateCb && controls.startDateCb.checked) controls.startDateCb.checked = false;
            if (controls.endDateCb && controls.endDateCb.checked) controls.endDateCb.checked = false;

            if (controls.allDatesBtn) {
                log(`جستجو در تمام تاریخ‌ها (All) برای: "${targetName || state.searchPid || state.searchNid || "همه"}"...`, "success");
                controls.allDatesBtn.click();
                return;
            }
        } else if (state.searchDatePreset === "TODAY" && controls.todayBtn) {
            log(`جستجو در بیماران امروز (Today) برای: "${targetName || "همه"}"...`, "success");
            controls.todayBtn.click();
            return;
        } else if (state.searchDatePreset === "YESTERDAY" && controls.yesterdayBtn) {
            log(`جستجو در بیماران دیروز (Yesterday) برای: "${targetName || "همه"}"...`, "success");
            controls.yesterdayBtn.click();
            return;
        } else if (state.searchDatePreset === "LASTWEEK" && controls.lastWeekBtn) {
            log(`جستجو در هفته اخیر (Last Week) برای: "${targetName || "همه"}"...`, "success");
            controls.lastWeekBtn.click();
            return;
        }

        if (controls.searchBtn) {
            log(`اجرای جستجو (Search) با عبارت: "${targetName || state.searchPid || state.searchNid || "همه"}"`, "success");
            controls.searchBtn.click();
        }
    }

    // Parse patient rows currently visible on Default.aspx
    function getPatientRowsOnDefaultPage() {
        const trs = Array.from(document.querySelectorAll('tr[onclick*="OnSelect"]'));
        return trs.map((tr, idx) => {
            const tds = Array.from(tr.querySelectorAll("td"));
            return {
                index: idx,
                tr,
                pid: (tds[1]?.textContent || "").trim(),
                name: (tds[2]?.textContent || "").trim(),
                nid: (tds[3]?.textContent || "").trim(),
                mobile: (tds[4]?.textContent || "").trim(),
                physician: (tds[5]?.textContent || "").trim(),
                sex: (tds[6]?.textContent || "").trim(),
                age: (tds[7]?.textContent || "").trim(),
                modality: (tds[8]?.textContent || "").trim(),
                serCount: parseInt((tds[9]?.textContent || "1").trim(), 10) || 1,
                imgCount: parseInt((tds[10]?.textContent || "1").trim(), 10) || 1,
                date: (tds[11]?.textContent || "").trim(),
                time: (tds[12]?.textContent || "").trim(),
                report: (tds[13]?.textContent || "").trim(),
                hospital: (tds[14]?.textContent || "").trim()
            };
        });
    }

    function triggerDefaultPageView() {
        const win = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
        if (typeof win.OnView === "function") {
            win.OnView();
            return;
        }
        const viewBtn = document.querySelector('#bView_imgMain, [onclick*="OnView"]');
        if (viewBtn) viewBtn.click();
    }

    // Detect when user clicks a row on Default.aspx so the Download tab shows that patient's info!
    function detectSelectedRowOnDefaultPage() {
        if (!isSearchPage) return;
        const hfKeys = document.getElementById("hfSelectedKeys");
        const hfRows = document.getElementById("hfSelectedRows");
        const selectedKey = hfKeys ? (hfKeys.value || "").replace(/[,;]+$/, "").trim() : "";
        const selectedRowIdx = hfRows && hfRows.value !== "" ? parseInt(hfRows.value, 10) : -1;

        const rows = getPatientRowsOnDefaultPage();
        let chosen = null;
        if (selectedRowIdx >= 0 && rows[selectedRowIdx]) {
            chosen = rows[selectedRowIdx];
        } else {
            // Check highlighted row by background/class or clicked tracking
            chosen = state.selectedRowOnDefault;
        }

        if (chosen) {
            state.patientName = (chosen.name || "Patient").replace(/[\^]/g, "_").replace(/\s+/g, "_");
            state.patientID = chosen.pid || "";
            state.modality = chosen.modality || "CT";
            if (selectedKey && !selectedKey.includes("=")) {
                state.studyKey = selectedKey;
            }
        }
    }

    // =========================================================================
    // MODULE D: Cross-Hospital Live Search Across HH, VH, and SBH
    // =========================================================================
    function requestPostText(url, formDataStr, refererUrl) {
        return new Promise((resolve) => {
            if (typeof GM_xmlhttpRequest !== "undefined") {
                GM_xmlhttpRequest({
                    method: "POST",
                    url,
                    data: formDataStr,
                    headers: {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": refererUrl || url
                    },
                    timeout: 15000,
                    onload: res => resolve(res && res.status >= 200 && res.status < 400 ? res.responseText : null),
                    onerror: () => resolve(null),
                    ontimeout: () => resolve(null)
                });
            } else {
                resolve(null);
            }
        });
    }

    function parseRowsFromHtmlDoc(doc, hospObj, appBasePath) {
        const trs = Array.from(doc.querySelectorAll('tr[onclick*="OnSelect"]'));
        return trs.map(tr => {
            const tds = Array.from(tr.querySelectorAll("td"));
            return {
                hospCode: hospObj.code,
                hospName: hospObj.name,
                origin: hospObj.origin,
                appBasePath,
                pid: (tds[1]?.textContent || "").trim(),
                name: (tds[2]?.textContent || "").trim(),
                nid: (tds[3]?.textContent || "").trim(),
                modality: (tds[8]?.textContent || "").trim(),
                serCount: (tds[9]?.textContent || "").trim(),
                imgCount: (tds[10]?.textContent || "").trim(),
                date: (tds[11]?.textContent || "").trim(),
                time: (tds[12]?.textContent || "").trim()
            };
        }).filter(r => r.pid || r.name);
    }

    async function searchSingleHospitalRemote(hosp, queryVariant, pidFilter, nidFilter) {
        const candidatePaths = hosp.code === "SBH" ? ["/MedalWeb", "/Medalwebpro"] : ["/Medalwebpro", "/MedalWeb"];
        let basePath = candidatePaths[0];
        let html = null;

        for (const p of candidatePaths) {
            html = await requestText(`${hosp.origin}${p}/Default.aspx`);
            if (html && (html.includes("__VIEWSTATE") || html.includes("Forgot password?"))) {
                basePath = p;
                break;
            }
        }

        if (!html) return { hosp, basePath, loggedIn: false, rows: [], error: "عدم پاسخ سرور" };

        const parser = new DOMParser();
        let doc = parser.parseFromString(html, "text/html");

        // Check if on Login.aspx
        if (html.includes("Forgot password?") || doc.querySelector('input[type="password"]')) {
            // Perform automatic background login via POST!
            const loginUrl = `${hosp.origin}${basePath}/Login.aspx`;
            const loginHtml = html.includes("__VIEWSTATE") ? html : await requestText(loginUrl);
            if (loginHtml) {
                const loginDoc = parser.parseFromString(loginHtml, "text/html");
                const formParams = new URLSearchParams();
                Array.from(loginDoc.querySelectorAll("input")).forEach(inp => {
                    if (!inp.name) return;
                    if (inp.type === "password") formParams.set(inp.name, DEFAULT_CREDENTIALS.password);
                    else if (inp.type === "text" || !inp.type) formParams.set(inp.name, DEFAULT_CREDENTIALS.username);
                    else if (inp.type === "hidden" || inp.type === "submit") formParams.set(inp.name, inp.value || "");
                });
                await requestPostText(loginUrl, formParams.toString(), loginUrl);
                html = await requestText(`${hosp.origin}${basePath}/Default.aspx`);
                if (html) doc = parser.parseFromString(html, "text/html");
            }
        }

        if (!html || html.includes("Forgot password?")) {
            return { hosp, basePath, loggedIn: false, rows: [], error: "نیاز به ورود (کلیک کنید)" };
        }

        // Now perform POST search on Default.aspx using __VIEWSTATE
        const vs = doc.querySelector('#__VIEWSTATE')?.value || "";
        const vsg = doc.querySelector('#__VIEWSTATEGENERATOR')?.value || "";
        const ev = doc.querySelector('#__EVENTVALIDATION')?.value || "";

        if (vs && (queryVariant || pidFilter || nidFilter || state.searchDatePreset !== "TODAY")) {
            const postParams = new URLSearchParams();
            postParams.set("__EVENTTARGET", "");
            postParams.set("__EVENTARGUMENT", "");
            postParams.set("__LASTFOCUS", "");
            postParams.set("__VIEWSTATE", vs);
            if (vsg) postParams.set("__VIEWSTATEGENERATOR", vsg);
            if (ev) postParams.set("__EVENTVALIDATION", ev);

            postParams.set("ctl09", queryVariant || "");
            postParams.set("ctl10", nidFilter || "");
            postParams.set("ctl16", pidFilter || "");
            postParams.set("ctl14", "");
            postParams.set("ctl15", "");
            postParams.set("ctl20", "");

            if (state.searchDatePreset === "TODAY") {
                postParams.set("bToday$imgMain.x", "12");
                postParams.set("bToday$imgMain.y", "12");
            } else if (state.searchDatePreset === "YESTERDAY") {
                postParams.set("bYesterday$imgMain.x", "12");
                postParams.set("bYesterday$imgMain.y", "12");
            } else if (state.searchDatePreset === "LASTWEEK") {
                postParams.set("bLastWeek$imgMain.x", "12");
                postParams.set("bLastWeek$imgMain.y", "12");
            } else {
                // ALL DATES search!
                postParams.set("bAllDates$imgMain.x", "12");
                postParams.set("bAllDates$imgMain.y", "12");
            }

            const defaultUrl = `${hosp.origin}${basePath}/Default.aspx`;
            const postHtml = await requestPostText(defaultUrl, postParams.toString(), defaultUrl);
            if (postHtml && !postHtml.includes("Forgot password?")) {
                doc = parser.parseFromString(postHtml, "text/html");
            }
        }

        let rows = parseRowsFromHtmlDoc(doc, hosp, basePath);

        // Client-side fuzzy filter if modality or multi-part name was given
        if (state.searchModality && state.searchModality !== "ALL") {
            rows = rows.filter(r => r.modality.toUpperCase() === state.searchModality);
        }

        return { hosp, basePath, loggedIn: true, rows: rows.slice(0, 25), error: null };
    }

    async function searchAcrossAllThreeHospitals() {
        if (!ui.multiResultsBox) return;
        const persianVal = (ui.persianInput?.value || "").trim();
        const pidVal = (ui.pidInput?.value || "").trim();
        const nidVal = (ui.nidInput?.value || "").trim();

        const { primary, variants } = generateSearchVariants(persianVal);
        // Use a 4-5 letter root prefix if searching by Persian name so spelling differences (FAZELI vs FAZELY, RASTGOO vs RASTGO) are all returned by PACS!
        let rootQuery = primary;
        if (primary && !primary.includes(" ") && !primary.includes("^") && primary.length >= 6) {
            rootQuery = primary.slice(0, 5);
        }

        ui.multiResultsBox.innerHTML = `<div style="color:#fbbf24; font-size:10px; padding:4px;">⏳ در حال جستجوی همزمان در هر ۳ بیمارستان (حشمتیه، واسطی، شهید بهشتی)...</div>`;
        log(`شروع جستجوی همزمان ۳ بیمارستان با ریشه: "${rootQuery || pidVal || nidVal || "همه"}"`, "warning");

        const results = await Promise.all(
            HOSPITALS.map(h => searchSingleHospitalRemote(h, rootQuery, pidVal, nidVal))
        );

        const htmlParts = [];
        let totalFound = 0;

        for (const res of results) {
            totalFound += res.rows.length;
            const badgeColor = res.loggedIn ? "#4ade80" : "#fbbf24";
            const statusLabel = res.loggedIn ? `${res.rows.length} نتیجه` : (res.error || "نیاز به ورود");
            const openHospUrl = `${res.hosp.origin}${res.basePath}/Default.aspx` +
                (primary || pidVal ? `?tg_name=${encodeURIComponent(primary)}&tg_pid=${encodeURIComponent(pidVal)}` : "");

            htmlParts.push(`
                <div style="background:rgba(15,23,42,0.9); border:1px solid rgba(56,189,248,0.3); border-radius:5px; padding:5px; margin-bottom:5px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <b style="color:#38bdf8; font-size:10px;">🏥 ${res.hosp.name}</b>
                        <div style="display:flex; align-items:center; gap:6px;">
                            <span style="color:${badgeColor}; font-size:9px;">${statusLabel}</span>
                            <a href="${openHospUrl}" target="_blank" style="padding:2px 6px; background:#0284c7; color:#fff; border-radius:3px; text-decoration:none; font-size:9px;">ورود به مرکز</a>
                        </div>
                    </div>
            `);

            if (res.rows.length === 0) {
                htmlParts.push(`<div style="color:#64748b; font-size:9px; padding:2px 0;">موردی یافت نشد.</div>`);
            } else {
                for (const row of res.rows.slice(0, 8)) {
                    const directViewUrl = `${res.hosp.origin}${res.basePath}/Default.aspx?tg_pid=${encodeURIComponent(row.pid)}&tg_autoview=1`;
                    htmlParts.push(`
                        <div style="display:flex; justify-content:space-between; align-items:center; padding:3px 4px; border-top:1px solid rgba(255,255,255,0.06); font-size:10px;">
                            <div style="direction:ltr; text-align:left; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:210px;">
                                <b style="color:#fcd34d;">${row.name}</b>
                                <span style="color:#94a3b8; font-size:9px;">[${row.modality} | ${row.imgCount}f | ${row.date}]</span>
                            </div>
                            <a href="${directViewUrl}" target="_blank" style="padding:2px 5px; background:#059669; color:#fff; border-radius:3px; text-decoration:none; font-size:9px; white-space:nowrap;">👁️ مشاهده ویوئر</a>
                        </div>
                    `);
                }
            }
            htmlParts.push(`</div>`);
        }

        ui.multiResultsBox.innerHTML = htmlParts.join("");
        log(`جستجوی ۳ بیمارستان کامل شد (${totalFound} بیمار یافت شد).`, "success");
        setStatus(`${totalFound} بیمار در ۳ بیمارستان یافت شد`, "success");
    }

    // Export technical DOM structure of Login.aspx / Default.aspx (zero patient PII!)
    function exportBotTechnicalSchema() {
        const inputs = Array.from(document.querySelectorAll("input, select, textarea, button"))
            .filter(el => !isInsideOurPanel(el))
            .map(el => ({
                tag: el.tagName.toLowerCase(),
                type: el.type || "",
                id: el.id || "",
                name: el.name || "",
                placeholder: el.placeholder || "",
                className: el.className || "",
                onclick: el.getAttribute("onclick") || ""
            }));

        const schema = {
            exportedAt: new Date().toISOString(),
            url: window.location.origin + window.location.pathname,
            appBasePath: getAppBasePath(),
            forms: Array.from(document.forms).map(f => ({ id: f.id, name: f.name, action: f.action, method: f.method })),
            inputs
        };

        const jsonStr = JSON.stringify(schema, null, 2);
        const blob = new Blob([jsonStr], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `medal_pacs_bot_schema_${window.location.hostname.split(".")[0]}.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 4000);
        log("ساختار فرم استخراج شد.", "success");
    }

    // ==========================================
    // 1. DICOM Part 10 Generator (.dcm) [UNTOUCHED v12]
    // ==========================================
    function createDicomPart10(jpegBytes, meta) {
        const encoder = new TextEncoder();
        function padEven(b, pad = 0x20) {
            if (b.length % 2 !== 0) {
                const p = new Uint8Array(b.length + 1);
                p.set(b); p[b.length] = pad; return p;
            }
            return b;
        }
        function strBytes(str, pad = 0x20) { return padEven(encoder.encode(str || ""), pad); }

        const elements = [];
        function addElem(g, e, vr, val) { elements.push({ group: g, element: e, vr, valBytes: val }); }
        function addString(g, e, vr, s) { addElem(g, e, vr, strBytes(s, 0x20)); }
        function addUS(g, e, n) {
            const b = new Uint8Array(2);
            new DataView(b.buffer).setUint16(0, n, true);
            addElem(g, e, "US", b);
        }

        const baseUid = "1.2.826.0.1.3680043.9.7133.";
        const studyUid = meta.studyUid || (baseUid + "1." + (meta.studyKey || "1"));
        const seriesUid = meta.seriesUid || (studyUid + "." + (meta.seriesKey || "1"));
        const sopUid = meta.sopUid || (seriesUid + "." + (meta.instanceNumber || "1"));
        const sopClassUid = "1.2.840.10008.5.1.4.1.1.2"; // CT

        addString(0x0008, 0x0008, "CS", "ORIGINAL\\PRIMARY\\AXIAL");
        addString(0x0008, 0x0016, "UI", sopClassUid);
        addString(0x0008, 0x0018, "UI", sopUid);
        addString(0x0008, 0x0020, "DA", (meta.date || "").replace(/\D/g, "").slice(0, 8));
        addString(0x0008, 0x0030, "TM", (meta.time || "").replace(/\D/g, "").slice(0, 6));
        addString(0x0008, 0x0050, "SH", meta.accessionNumber || "");
        addString(0x0008, 0x0060, "CS", meta.modality || "CT");
        addString(0x0008, 0x0070, "LO", "Medal PACS");
        addString(0x0008, 0x0080, "LO", meta.institution || "Hospital");
        addString(0x0008, 0x1030, "LO", meta.studyDesc || "");
        addString(0x0008, 0x103E, "LO", meta.seriesDesc || "");

        addString(0x0010, 0x0010, "PN", meta.patientName || "Patient");
        addString(0x0010, 0x0020, "LO", meta.patientID || "");
        addString(0x0010, 0x0040, "CS", meta.patientSex || "");
        addString(0x0010, 0x1010, "AS", meta.patientAge || "");

        if (meta.sliceThickness) addString(0x0018, 0x0050, "DS", String(meta.sliceThickness));
        if (meta.kvp) addString(0x0018, 0x0060, "DS", String(meta.kvp));

        addString(0x0020, 0x000D, "UI", studyUid);
        addString(0x0020, 0x000E, "UI", seriesUid);
        addString(0x0020, 0x0011, "IS", String(meta.seriesNumber || meta.seriesKey || 1));
        addString(0x0020, 0x0013, "IS", String(meta.instanceNumber || 1));

        if (meta.imagePosition) addString(0x0020, 0x0032, "DS", meta.imagePosition);
        if (meta.imageOrientation) addString(0x0020, 0x0037, "DS", meta.imageOrientation);
        if (meta.sliceLocation) addString(0x0020, 0x1041, "DS", String(meta.sliceLocation));

        addUS(0x0028, 0x0002, 1);
        addString(0x0028, 0x0004, "CS", "MONOCHROME2");
        addUS(0x0028, 0x0010, meta.rows || 512);
        addUS(0x0028, 0x0011, meta.columns || 512);
        if (meta.pixelSpacing) addString(0x0028, 0x0030, "DS", meta.pixelSpacing);

        addUS(0x0028, 0x0100, 8);
        addUS(0x0028, 0x0101, 8);
        addUS(0x0028, 0x0102, 7);
        addUS(0x0028, 0x0103, 0);

        if (meta.windowCenter) addString(0x0028, 0x1050, "DS", String(meta.windowCenter));
        if (meta.windowWidth) addString(0x0028, 0x1051, "DS", String(meta.windowWidth));
        addString(0x0028, 0x1052, "DS", "0");
        addString(0x0028, 0x1053, "DS", "1");

        elements.sort((a, b) => (((a.group << 16) | a.element) >>> 0) - (((b.group << 16) | b.element) >>> 0));

        const metaElements = [];
        metaElements.push({ group: 0x0002, element: 0x0001, vr: "OB", valBytes: new Uint8Array([0x00, 0x01]) });
        metaElements.push({ group: 0x0002, element: 0x0002, vr: "UI", valBytes: strBytes(sopClassUid, 0x00) });
        metaElements.push({ group: 0x0002, element: 0x0003, vr: "UI", valBytes: strBytes(sopUid, 0x00) });
        metaElements.push({ group: 0x0002, element: 0x0010, vr: "UI", valBytes: strBytes("1.2.840.10008.1.2.4.50", 0x00) });
        metaElements.push({ group: 0x0002, element: 0x0012, vr: "UI", valBytes: strBytes(baseUid + "99", 0x00) });

        let metaBodyLen = 0;
        for (const el of metaElements) {
            metaBodyLen += 4 + 2;
            metaBodyLen += ["OB", "OW", "OF", "SQ", "UT", "UN"].includes(el.vr) ? 6 : 2;
            metaBodyLen += el.valBytes.length;
        }

        const group0002LenBytes = new Uint8Array(4);
        new DataView(group0002LenBytes.buffer).setUint32(0, metaBodyLen, true);
        metaElements.unshift({ group: 0x0002, element: 0x0000, vr: "UL", valBytes: group0002LenBytes });

        const paddedJpeg = (jpegBytes.length % 2 !== 0) ? new Uint8Array(jpegBytes.length + 1) : jpegBytes;
        if (jpegBytes.length % 2 !== 0) { paddedJpeg.set(jpegBytes); paddedJpeg[jpegBytes.length] = 0x00; }

        const pixelDataTotalLen = 12 + 8 + (8 + paddedJpeg.length) + 8;
        let totalSize = 128 + 4;
        function calcElemSize(el) {
            let s = 6;
            s += ["OB", "OW", "OF", "SQ", "UT", "UN"].includes(el.vr) ? 6 : 2;
            return s + el.valBytes.length;
        }
        for (const el of metaElements) totalSize += calcElemSize(el);
        for (const el of elements) totalSize += calcElemSize(el);
        totalSize += pixelDataTotalLen;

        const buffer = new Uint8Array(totalSize);
        const view = new DataView(buffer.buffer);
        let offset = 128;
        buffer[offset++] = 0x44; buffer[offset++] = 0x49; buffer[offset++] = 0x43; buffer[offset++] = 0x4D;

        function writeElem(el) {
            view.setUint16(offset, el.group, true); offset += 2;
            view.setUint16(offset, el.element, true); offset += 2;
            buffer[offset++] = el.vr.charCodeAt(0);
            buffer[offset++] = el.vr.charCodeAt(1);
            if (["OB", "OW", "OF", "SQ", "UT", "UN"].includes(el.vr)) {
                buffer[offset++] = 0; buffer[offset++] = 0;
                view.setUint32(offset, el.valBytes.length, true); offset += 4;
            } else {
                view.setUint16(offset, el.valBytes.length, true); offset += 2;
            }
            buffer.set(el.valBytes, offset); offset += el.valBytes.length;
        }

        for (const el of metaElements) writeElem(el);
        for (const el of elements) writeElem(el);

        view.setUint16(offset, 0x7FE0, true); offset += 2;
        view.setUint16(offset, 0x0010, true); offset += 2;
        buffer[offset++] = 0x4F; buffer[offset++] = 0x42;
        buffer[offset++] = 0x00; buffer[offset++] = 0x00;
        view.setUint32(offset, 0xFFFFFFFF, true); offset += 4;

        view.setUint16(offset, 0xFFFE, true); offset += 2;
        view.setUint16(offset, 0xE000, true); offset += 2;
        view.setUint32(offset, 0, true); offset += 4;

        view.setUint16(offset, 0xFFFE, true); offset += 2;
        view.setUint16(offset, 0xE000, true); offset += 2;
        view.setUint32(offset, paddedJpeg.length, true); offset += 4;
        buffer.set(paddedJpeg, offset); offset += paddedJpeg.length;

        view.setUint16(offset, 0xFFFE, true); offset += 2;
        view.setUint16(offset, 0xE0DD, true); offset += 2;
        view.setUint32(offset, 0, true); offset += 4;

        return buffer;
    }

    // ==========================================
    // 2. Binary Fast ZIP Packager [UNTOUCHED v12]
    // ==========================================
    const CRC32_TABLE = new Uint32Array(256);
    for (let i = 0; i < 256; i++) {
        let c = i;
        for (let j = 0; j < 8; j++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
        CRC32_TABLE[i] = c;
    }

    function calcCrc32(bytes) {
        let crc = 0xffffffff;
        for (let i = 0; i < bytes.length; i++) crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
        return (crc ^ 0xffffffff) >>> 0;
    }

    function buildFastZip(files) {
        const encoder = new TextEncoder();
        let totalSize = 0;

        const records = files.map(file => {
            const nameBytes = encoder.encode(file.name);
            const dataBytes = file.data instanceof Uint8Array ? file.data : new Uint8Array(file.data);
            const crc = calcCrc32(dataBytes);
            const localSize = 30 + nameBytes.length + dataBytes.length;
            const centralSize = 46 + nameBytes.length;
            totalSize += localSize + centralSize;
            return { nameBytes, dataBytes, crc, size: dataBytes.length, localSize, centralSize };
        });

        totalSize += 22;
        const buffer = new Uint8Array(totalSize);
        const view = new DataView(buffer.buffer);
        let localOffset = 0;

        for (const item of records) {
            item.offset = localOffset;
            view.setUint32(localOffset, 0x04034b50, true);
            view.setUint16(localOffset + 4, 20, true);
            view.setUint16(localOffset + 6, 0, true);
            view.setUint16(localOffset + 8, 0, true);
            view.setUint16(localOffset + 10, 0, true);
            view.setUint16(localOffset + 12, 0, true);
            view.setUint32(localOffset + 14, item.crc, true);
            view.setUint32(localOffset + 18, item.size, true);
            view.setUint32(localOffset + 22, item.size, true);
            view.setUint16(localOffset + 26, item.nameBytes.length, true);
            view.setUint16(localOffset + 28, 0, true);
            buffer.set(item.nameBytes, localOffset + 30);
            buffer.set(item.dataBytes, localOffset + 30 + item.nameBytes.length);
            localOffset += item.localSize;
        }

        let centralOffset = localOffset;
        for (const item of records) {
            view.setUint32(centralOffset, 0x02014b50, true);
            view.setUint16(centralOffset + 4, 20, true);
            view.setUint16(centralOffset + 6, 20, true);
            view.setUint16(centralOffset + 8, 0, true);
            view.setUint16(centralOffset + 10, 0, true);
            view.setUint16(centralOffset + 12, 0, true);
            view.setUint16(centralOffset + 14, 0, true);
            view.setUint32(centralOffset + 16, item.crc, true);
            view.setUint32(centralOffset + 20, item.size, true);
            view.setUint32(centralOffset + 24, item.size, true);
            view.setUint16(centralOffset + 28, item.nameBytes.length, true);
            view.setUint16(centralOffset + 30, 0, true);
            view.setUint16(centralOffset + 32, 0, true);
            view.setUint16(centralOffset + 34, 0, true);
            view.setUint16(centralOffset + 36, 0, true);
            view.setUint32(centralOffset + 38, 0, true);
            view.setUint32(centralOffset + 42, item.offset, true);
            buffer.set(item.nameBytes, centralOffset + 46);
            centralOffset += item.centralSize;
        }

        const centralDirSize = centralOffset - localOffset;
        view.setUint32(centralOffset, 0x06054b50, true);
        view.setUint16(centralOffset + 4, 0, true);
        view.setUint16(centralOffset + 6, 0, true);
        view.setUint16(centralOffset + 8, records.length, true);
        view.setUint16(centralOffset + 10, records.length, true);
        view.setUint32(centralOffset + 12, centralDirSize, true);
        view.setUint32(centralOffset + 16, localOffset, true);
        view.setUint16(centralOffset + 20, 0, true);

        return new Blob([buffer], { type: "application/zip" });
    }

    // ==========================================
    // 3. Metadata Discovery [UNTOUCHED v12 + Default.aspx row helper]
    // ==========================================
    function detectMetadata() {
        const win = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
        let study = null;
        if (win.Studies && win.Studies.length > 0) study = win.Studies[0];

        if (!study) {
            try {
                const scripts = document.getElementsByTagName("script");
                for (let i = 0; i < scripts.length; i++) {
                    const text = scripts[i].textContent || "";
                    const m = text.match(/var\s+Studies\s*=\s*(\[\s*\{[\s\S]*?\}\s*\]);/);
                    if (m) {
                        const parsed = (new Function(`return ${m[1]};`))();
                        if (parsed && parsed.length > 0) { study = parsed[0]; break; }
                    }
                }
            } catch (e) {}
        }

        if (study) {
            state.studyKey = String(study.Key || "");
            state.patientName = (study.Name || "Patient").trim().replace(/[\^]/g, "_").replace(/\s+/g, "_");
            state.patientID = study.ID || "";
            state.modality = study.Modality || "CT";
            if (study.Series && Array.isArray(study.Series)) state.seriesList = study.Series;
        } else if (isSearchPage) {
            detectSelectedRowOnDefaultPage();
        }

        if (win.curSer !== undefined && win.Series && win.Series[win.curSer]) {
            state.activeSeriesNdx = win.curSer;
            const activeSerObj = win.Series[win.curSer];
            if (activeSerObj.Ser && !state.selectedSeriesKey) state.selectedSeriesKey = String(activeSerObj.Ser);
            if (activeSerObj.WW && activeSerObj.WC) {
                state.ww = activeSerObj.WW;
                state.wc = activeSerObj.WC;
            }
        } else if (state.seriesList.length > 0 && !state.selectedSeriesKey) {
            let bestSer = state.seriesList[0];
            for (const s of state.seriesList) {
                if ((s.imgCount || 0) > (bestSer.imgCount || 0)) bestSer = s;
            }
            state.selectedSeriesKey = String(bestSer.Key);
        }
    }

    function updateSeriesDropdown() {
        if (!ui.seriesSelect) return;
        const currentVal = ui.seriesSelect.value;
        ui.seriesSelect.innerHTML = "";

        if (!state.seriesList || state.seriesList.length === 0) {
            const opt = document.createElement("option");
            opt.value = "";
            opt.textContent = isSearchPage
                ? "یک بیمار را دابل‌کلیک کنید تا وارد ویوئر شود..."
                : "در حال شناسایی سریها...";
            ui.seriesSelect.appendChild(opt);
            return;
        }

        for (const ser of state.seriesList) {
            const opt = document.createElement("option");
            opt.value = String(ser.Key);
            const desc = ser.Desc ? ser.Desc.trim() : `Series ${ser.Key}`;
            const count = ser.imgCount || 1;
            opt.textContent = `سری ${ser.Key}: ${desc} (${count} فریم)`;
            if (String(ser.Key) === String(state.selectedSeriesKey)) opt.selected = true;
            ui.seriesSelect.appendChild(opt);
        }

        if (state.seriesList.length > 1) {
            const optAll = document.createElement("option");
            optAll.value = "__ALL__";
            const totalAll = state.seriesList.reduce((acc, s) => acc + (s.imgCount || 0), 0);
            optAll.textContent = `★ دانلود تمام سریها (${totalAll} فریم)`;
            if (currentVal === "__ALL__") optAll.selected = true;
            ui.seriesSelect.appendChild(optAll);
        }

        if (ui.seriesSelect.value) state.selectedSeriesKey = ui.seriesSelect.value;
    }

    function refreshUIState() {
        const leftoverV12 = document.getElementById("pacs-v12-panel");
        if (leftoverV12) leftoverV12.remove();
        if (isRunning) return;

        detectMetadata();
        updateSeriesDropdown();

        if (ui.metaBox) {
            const isReady = Boolean(state.studyKey && state.seriesList.length > 0);
            const activeSer = state.seriesList.find(s => String(s.Key) === String(state.selectedSeriesKey)) || state.seriesList[0];
            const sliceCount = state.selectedSeriesKey === "__ALL__"
                ? state.seriesList.reduce((acc, s) => acc + (s.imgCount || 0), 0)
                : (activeSer ? activeSer.imgCount : 0);

            ui.metaBox.innerHTML = `
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span style="color:#94a3b8">بیمار:</span>
                    <b style="color:#fcd34d">${state.patientName} (${state.modality})</b>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span style="color:#94a3b8">شناسه بیمار:</span>
                    <b style="color:#e2e8f0; font-family:monospace;">${state.patientID || "—"}</b>
                </div>
                <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                    <span style="color:#94a3b8">کد آزمون (SK):</span>
                    <b style="color:#38bdf8; font-family:monospace;">${state.studyKey || (isSearchPage ? "در لیست (دکمه View را بزنید)" : "—")}</b>
                </div>
                <div style="display:flex; justify-content:space-between;">
                    <span style="color:#94a3b8">تعداد اسلایس:</span>
                    <b style="color:#4ade80">${sliceCount} فریم [${state.outputFormat}]</b>
                </div>
            `;
            ui.startBtn.disabled = !isReady || sliceCount === 0;
            if (ui.openViewerBtn) {
                ui.openViewerBtn.style.display = isSearchPage ? "block" : "none";
            }
        }

        // Toggle video options panel visibility
        if (ui.videoOptionsBox) {
            ui.videoOptionsBox.style.display = (state.outputFormat === "VIDEO") ? "block" : "none";
        }
    }

    // ==========================================
    // 4. Network Fetchers [UNTOUCHED v12]
    // ==========================================
    function requestText(url) {
        return new Promise((resolve) => {
            if (typeof GM_xmlhttpRequest !== "undefined") {
                GM_xmlhttpRequest({
                    method: "GET", url,
                    headers: { "Accept": "text/xml, application/xml, */*", "Referer": window.location.href },
                    timeout: 10000,
                    onload: res => resolve(res && res.status === 200 ? res.responseText : null),
                    onerror: () => resolve(null), ontimeout: () => resolve(null)
                });
            } else {
                fetch(url, { credentials: "include" })
                    .then(res => res.ok ? res.text() : null)
                    .then(t => resolve(t)).catch(() => resolve(null));
            }
        });
    }

    function requestBinary(url) {
        return new Promise((resolve) => {
            if (typeof GM_xmlhttpRequest !== "undefined") {
                GM_xmlhttpRequest({
                    method: "GET", url, responseType: "arraybuffer",
                    headers: { "Accept": "image/jpeg,image/*,*/*", "Referer": window.location.href },
                    timeout: 12000,
                    onload: res => resolve(res && res.status === 200 && res.response && res.response.byteLength > 400 ? new Uint8Array(res.response) : null),
                    onerror: () => resolve(null), ontimeout: () => resolve(null)
                });
            } else {
                fetch(url, { credentials: "include" })
                    .then(res => res.ok ? res.arrayBuffer() : null)
                    .then(b => resolve(b && b.byteLength > 400 ? new Uint8Array(b) : null))
                    .catch(() => resolve(null));
            }
        });
    }

    function parseXmlTag(xml, tag) {
        const m = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, "i"));
        return m ? m[1].trim() : "";
    }

    function getAppBasePath() {
        const pathname = window.location.pathname;
        const parts = pathname.split("/").filter(Boolean);
        if (parts.length > 1) {
            return "/" + parts.slice(0, -1).join("/");
        } else if (parts.length === 1 && !parts[0].includes(".")) {
            return "/" + parts[0];
        }
        return "";
    }

    async function fetchSliceBundle(studyKey, seriesKey, imgIndex, totalSlices) {
        const currentBase = getAppBasePath();
        const baseCandidates = [...new Set([
            currentBase,
            "/medalweb",
            "/Medalweb",
            "/MedalWeb",
            "/Medalwebpro",
            "/medalwebpro",
            ""
        ])];

        let xml = null;
        let successfulBase = currentBase;

        for (const b of baseCandidates) {
            const apiPath = `${window.location.origin}${b}/GetImage.aspx?SK=${studyKey}&Ser=${seriesKey}&Img=${imgIndex}&Manipulate=0`;
            for (let att = 1; att <= 2; att++) {
                xml = await requestText(apiPath);
                if (xml && xml.includes("<Address>")) {
                    successfulBase = b;
                    break;
                }
                await sleep(att * 100);
            }
            if (xml && xml.includes("<Address>")) break;
        }

        if (!xml || !xml.includes("<Address>")) return null;

        const address = parseXmlTag(xml, "Address");
        if (!address) return null;

        const cacherCandidates = [...new Set([
            `${window.location.origin}/Cacher/${address}`,
            `${window.location.origin}${successfulBase}/Cacher/${address}`,
            `${window.location.origin}/medalweb/Cacher/${address}`,
            `${window.location.origin}/MedalWeb/Cacher/${address}`,
            `${window.location.origin}/Medalwebpro/Cacher/${address}`
        ])];

        let jpegBytes = null;
        for (const cUrl of cacherCandidates) {
            for (let att = 1; att <= 2; att++) {
                jpegBytes = await requestBinary(cUrl);
                if (jpegBytes && jpegBytes.byteLength > 400) break;
                await sleep(att * 120);
            }
            if (jpegBytes && jpegBytes.byteLength > 400) break;
        }

        if (!jpegBytes) return null;

        let imagePosition = "";
        let imageOrientation = "";
        const geom = parseXmlTag(xml, "Geometry");
        if (geom && geom !== "none") {
            const parts = geom.split("!");
            if (parts.length >= 3) {
                imagePosition = parts[0].split(",").map(v => v.trim()).join("\\");
                imageOrientation = `${parts[1].split(",").map(v => v.trim()).join("\\")}\\${parts[2].split(",").map(v => v.trim()).join("\\")}`;
            }
        }

        const psRaw = parseXmlTag(xml, "PS");
        const pixelSpacing = psRaw ? psRaw.replace(",", "\\") : "";

        const sliceMeta = {
            studyKey, seriesKey,
            seriesNumber: parseInt(seriesKey, 10) || 1,
            instanceNumber: imgIndex,
            totalSlices: totalSlices || 1,
            patientName: parseXmlTag(xml, "PName") || state.patientName,
            patientID: parseXmlTag(xml, "PID") || state.patientID,
            patientSex: parseXmlTag(xml, "PSex"),
            patientAge: parseXmlTag(xml, "PAge"),
            modality: parseXmlTag(xml, "Mod") || state.modality,
            date: parseXmlTag(xml, "AcqDate") || parseXmlTag(xml, "Study-Date"),
            time: parseXmlTag(xml, "AcqTime") || parseXmlTag(xml, "Study-Time"),
            accessionNumber: parseXmlTag(xml, "AccessionNumber"),
            studyDesc: parseXmlTag(xml, "StudyDesc"),
            seriesDesc: parseXmlTag(xml, "SeriesDesc"),
            institution: parseXmlTag(xml, "Hospital"),
            rows: parseInt(parseXmlTag(xml, "Height"), 10) || 512,
            columns: parseInt(parseXmlTag(xml, "Width"), 10) || 512,
            pixelSpacing,
            sliceThickness: parseXmlTag(xml, "Slice-Thickness"),
            sliceLocation: parseXmlTag(xml, "Slice-Location"),
            kvp: parseXmlTag(xml, "KVP"),
            imagePosition, imageOrientation,
            windowCenter: parseXmlTag(xml, "WC"),
            windowWidth: parseXmlTag(xml, "WW")
        };

        return { jpegBytes, meta: sliceMeta };
    }

    // =========================================================
    // 5. Medical Cine Video Engine (HTML5 Canvas + MediaRecorder) [UNTOUCHED v12]
    // =========================================================
    function createBitmapFromJpeg(jpegBytes) {
        return new Promise((resolve) => {
            const blob = new Blob([jpegBytes], { type: "image/jpeg" });
            const url = URL.createObjectURL(blob);
            const img = new Image();
            img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
            img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
            img.src = url;
        });
    }

    function renderMedicalHUD(ctx, width, height, meta) {
        ctx.save();
        ctx.font = "14px 'Lucida Console', Monaco, monospace, sans-serif";
        ctx.fillStyle = "#ffffff";
        ctx.textBaseline = "top";

        // Top-Left: Slice / Total, StudyDesc, Date
        const tlText1 = `${meta.instanceNumber} / ${meta.totalSlices} ${meta.studyDesc || ""} ${meta.date || ""}`;
        ctx.fillText(tlText1, 16, 16);

        // Top-Center: Compass 'A' (Anterior)
        ctx.fillStyle = "#facc15";
        ctx.textAlign = "center";
        ctx.fillText("A", width / 2, 16);

        // Top-Right: Hospital & Timestamp
        ctx.fillStyle = "#ffffff";
        ctx.textAlign = "right";
        ctx.fillText(meta.institution || "HESHMATIE", width - 16, 16);
        ctx.fillText(`${meta.date || ""} ${meta.time || ""}`, width - 16, 36);

        // Left-Center: Compass 'R' (Right)
        ctx.fillStyle = "#facc15";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText("R", 16, height / 2);

        // Right-Center: Compass 'L' (Left) & Scale Bar
        ctx.textAlign = "right";
        ctx.fillText("L", width - 16, height / 2);
        // 10cm Scale bar
        ctx.strokeStyle = "#e2e8f0";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(width - 24, height / 2 - 40);
        ctx.lineTo(width - 24, height / 2 + 40);
        ctx.stroke();
        ctx.fillStyle = "#94a3b8";
        ctx.font = "10px monospace";
        ctx.fillText("10cm", width - 30, height / 2);

        // Bottom-Center: Compass 'P' (Posterior)
        ctx.fillStyle = "#facc15";
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillText("P", width / 2, height - 16);

        // Bottom-Left: Detailed Acquisition Parameters
        ctx.fillStyle = "#ffffff";
        ctx.textAlign = "left";
        ctx.font = "13px 'Lucida Console', Monaco, monospace";
        const lines = [
            `im: ${meta.instanceNumber} / ${meta.totalSlices}`,
            `se: ${meta.seriesNumber}`,
            `KVP: ${meta.kvp || 130}`,
            `SL: ${meta.sliceLocation || ""}`,
            `Thickness: ${meta.sliceThickness || 3}mm`,
            `Zoom: 100%`
        ];
        let yOffset = height - 16 - (lines.length * 18);
        for (const line of lines) {
            ctx.fillText(line, 16, yOffset);
            yOffset += 18;
        }

        // Bottom-Right: Windowing info
        if (meta.windowWidth && meta.windowCenter) {
            ctx.textAlign = "right";
            ctx.fillText(`W: ${meta.windowWidth} L: ${meta.windowCenter}`, width - 16, height - 16);
        }

        ctx.restore();
    }

    async function encodeCineVideo(sliceBundles, fps, playMode, includeOverlay, seriesName) {
        log(`در حال پردازش ویدیو سینمایی با نرخ ${fps} فریم بر ثانیه...`, "warning");

        const targetW = 1024;
        const targetH = 1024;
        const canvas = document.createElement("canvas");
        canvas.width = targetW;
        canvas.height = targetH;
        const ctx = canvas.getContext("2d");

        setStatus("آمادهسازی لایههای تصویر در حافظه گرافیکی...", "warning");
        const renderedFrames = [];
        for (let i = 0; i < sliceBundles.length; i++) {
            const bmp = await createBitmapFromJpeg(sliceBundles[i].jpegBytes);
            if (bmp) {
                renderedFrames.push({ img: bmp, meta: sliceBundles[i].meta });
            }
        }

        if (renderedFrames.length === 0) throw new Error("هیچ فریمی برای تولید ویدیو آماده نشد.");

        const sequence = [];
        for (let i = 0; i < renderedFrames.length; i++) sequence.push(renderedFrames[i]);
        if (playMode === "PINGPONG" && renderedFrames.length > 2) {
            for (let i = renderedFrames.length - 2; i > 0; i--) sequence.push(renderedFrames[i]);
        }

        let mimeType = "video/webm";
        let ext = "webm";
        if (typeof MediaRecorder !== "undefined") {
            if (MediaRecorder.isTypeSupported("video/mp4;codecs=avc1")) {
                mimeType = "video/mp4;codecs=avc1"; ext = "mp4";
            } else if (MediaRecorder.isTypeSupported("video/mp4")) {
                mimeType = "video/mp4"; ext = "mp4";
            } else if (MediaRecorder.isTypeSupported("video/webm;codecs=vp9")) {
                mimeType = "video/webm;codecs=vp9"; ext = "webm";
            }
        }

        const stream = canvas.captureStream(fps);
        const recorder = new MediaRecorder(stream, {
            mimeType,
            videoBitsPerSecond: 10000000
        });

        const chunks = [];
        recorder.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };

        const completionPromise = new Promise(resolve => {
            recorder.onstop = () => {
                const videoBlob = new Blob(chunks, { type: mimeType });
                resolve({ videoBlob, ext });
            };
        });

        recorder.start();

        const frameIntervalMs = 1000 / fps;
        const totalFrames = sequence.length;

        for (let f = 0; f < totalFrames; f++) {
            if (stopRequested) break;

            const frame = sequence[f];

            ctx.fillStyle = "#000000";
            ctx.fillRect(0, 0, targetW, targetH);

            const imgAspect = frame.img.width / frame.img.height;
            let drawW = targetW;
            let drawH = targetH;
            if (imgAspect > 1) drawH = targetW / imgAspect;
            else drawW = targetH * imgAspect;
            const drawX = (targetW - drawW) / 2;
            const drawY = (targetH - drawH) / 2;
            ctx.drawImage(frame.img, drawX, drawY, drawW, drawH);

            if (includeOverlay) {
                renderMedicalHUD(ctx, targetW, targetH, frame.meta);
            }

            ui.progressBar.value = f + 1;
            ui.progressBar.max = totalFrames;
            const pct = Math.round(((f + 1) / totalFrames) * 100);
            ui.percentText.textContent = `${pct}%`;
            setStatus(`رندر ویدیویی: فریم ${f + 1} از ${totalFrames} (${fps} FPS)`, "warning");

            await sleep(frameIntervalMs);
        }

        recorder.stop();
        return await completionPromise;
    }

    // ==========================================
    // 6. Main Orchestrator [UNTOUCHED v12]
    // ==========================================
    async function startDownload() {
        if (isRunning) return;

        refreshUIState();

        if (!state.studyKey || state.seriesList.length === 0) {
            log("لطفاً ابتدا بیمار را دابل‌کلیک کنید (یا دکمه View بالای صفحه را بزنید) تا وارد صفحه ویوئر شوید.", "error");
            return;
        }

        isRunning = true;
        stopRequested = false;
        ui.startBtn.disabled = true;
        ui.stopBtn.disabled = false;
        ui.seriesSelect.disabled = true;
        ui.formatSelect.disabled = true;

        const isVideo = state.outputFormat === "VIDEO";
        const isDicom = state.outputFormat === "DICOM";

        const targetSeriesList = state.selectedSeriesKey === "__ALL__"
            ? state.seriesList
            : state.seriesList.filter(s => String(s.Key) === String(state.selectedSeriesKey));

        const totalSlices = targetSeriesList.reduce((acc, s) => acc + (s.imgCount || 0), 0);
        log(`شروع دریافت ${totalSlices} اسلایس با فرمت ${state.outputFormat} (${state.patientName})...`, "warning");

        ui.progressBar.max = totalSlices;
        ui.progressBar.value = 0;
        ui.percentText.textContent = "0%";

        const filesToZip = [];
        let completedCount = 0;

        try {
            for (const ser of targetSeriesList) {
                if (stopRequested) break;

                const serKey = String(ser.Key);
                const serDesc = (ser.Desc || `Series_${serKey}`).trim().replace(/[\^\\\/:\*\?"<>\|]/g, "_").replace(/\s+/g, "_");
                const count = ser.imgCount || 1;

                log(`دریافت سری ${serKey}: ${serDesc} (${count} فریم)...`, "info");

                const queue = [];
                for (let i = 1; i <= count; i++) queue.push(i);

                const downloadedSlices = new Map();
                const concurrency = 4;

                async function worker() {
                    while (queue.length > 0 && !stopRequested) {
                        const sliceNdx = queue.shift();
                        const result = await fetchSliceBundle(state.studyKey, serKey, sliceNdx, count);
                        if (result) {
                            downloadedSlices.set(sliceNdx, result);
                            completedCount++;
                            ui.progressBar.value = completedCount;
                            const pct = Math.round((completedCount / totalSlices) * 100);
                            ui.percentText.textContent = `${pct}%`;
                            setStatus(`دریافت شد: ${completedCount} از ${totalSlices} فریم`, "warning");
                        } else {
                            log(`خطا در دریافت اسلایس ${sliceNdx} سری ${serKey}`, "error");
                        }
                        await sleep(30);
                    }
                }

                const workers = [];
                for (let w = 0; w < concurrency; w++) workers.push(worker());
                await Promise.all(workers);

                if (stopRequested) break;

                for (let i = 1; i <= count; i++) {
                    if (!downloadedSlices.has(i) && !stopRequested) {
                        log(`بازخوانی مجدد اسلایس ${i}...`, "warning");
                        const result = await fetchSliceBundle(state.studyKey, serKey, i, count);
                        if (result) {
                            downloadedSlices.set(i, result);
                            completedCount++;
                            ui.progressBar.value = completedCount;
                            ui.percentText.textContent = `${Math.round((completedCount / totalSlices) * 100)}%`;
                        }
                    }
                }

                if (isVideo) {
                    const sortedBundles = [];
                    for (let i = 1; i <= count; i++) {
                        if (downloadedSlices.has(i)) sortedBundles.push(downloadedSlices.get(i));
                    }

                    const { videoBlob, ext } = await encodeCineVideo(sortedBundles, state.fps, state.playMode, state.includeOverlay, serDesc);
                    const videoUrl = URL.createObjectURL(videoBlob);
                    const videoFileName = `${state.patientName}_${state.modality}_${serDesc}_${state.fps}FPS_${state.playMode}.${ext}`;

                    const a = document.createElement("a");
                    a.href = videoUrl;
                    a.download = videoFileName;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    setTimeout(() => URL.revokeObjectURL(videoUrl), 5000);

                    log(`ویدیو ${videoFileName} با موفقیت دانلود شد.`, "success");
                    setStatus(`ویدیو با موفقیت ساخته شد (${state.fps} FPS)`, "success");

                } else {
                    const ext = isDicom ? "dcm" : "jpg";
                    for (let i = 1; i <= count; i++) {
                        if (downloadedSlices.has(i)) {
                            const res = downloadedSlices.get(i);
                            const fileData = isDicom ? createDicomPart10(res.jpegBytes, res.meta) : res.jpegBytes;
                            const fileName = targetSeriesList.length > 1
                                ? `Ser${String(serKey).padStart(2, "0")}_${serDesc}/Slice_${String(i).padStart(3, "0")}.${ext}`
                                : `${state.patientName}_${serDesc}_Slice_${String(i).padStart(3, "0")}.${ext}`;
                            filesToZip.push({ name: fileName, data: fileData });
                        }
                    }
                }
            }

            if (stopRequested) {
                log("عملیات توسط کاربر متوقف شد.", "warning");
                setStatus("عملیات متوقف شد", "warning");
                return;
            }

            if (!isVideo && filesToZip.length > 0) {
                setStatus("در حال بستهبندی فایل ZIP در حافظه...", "warning");
                await sleep(50);

                const zipBlob = buildFastZip(filesToZip);
                const zipUrl = URL.createObjectURL(zipBlob);

                const activeSerDesc = targetSeriesList.length === 1
                    ? (targetSeriesList[0].Desc || `Series${targetSeriesList[0].Key}`).trim().replace(/[^a-zA-Z0-9_\-]/g, "_")
                    : "AllSeries";
                const finalFilename = `${state.patientName}_${state.modality}_${activeSerDesc}_${filesToZip.length}${state.outputFormat}.zip`;

                const a = document.createElement("a");
                a.href = zipUrl;
                a.download = finalFilename;
                document.body.appendChild(a);
                a.click();
                a.remove();
                setTimeout(() => URL.revokeObjectURL(zipUrl), 5000);

                setStatus(`۱۰۰٪ دانلود شد (${filesToZip.length} فایل ${state.outputFormat})`, "success");
                log(`بسته کامل ${finalFilename} با موفقیت ذخیره شد.`, "success");
            }
        } catch (err) {
            log(err.message, "error");
            setStatus("خطا در فرایند دانلود", "error");
        } finally {
            isRunning = false;
            ui.startBtn.disabled = false;
            ui.stopBtn.disabled = true;
            ui.seriesSelect.disabled = false;
            ui.formatSelect.disabled = false;
        }
    }

    // ==========================================
    // 7. Interactive Modern Glassmorphism UI (v13.1 Debugged)
    // ==========================================
    function switchTab(tabName) {
        state.activeTab = tabName;
        if (!ui.tabContentDownload || !ui.tabContentSearch) return;
        if (tabName === "DOWNLOAD") {
            ui.tabContentDownload.style.display = "block";
            ui.tabContentSearch.style.display = "none";
            ui.tabBtnDownload.style.background = "#0284c7";
            ui.tabBtnDownload.style.color = "#ffffff";
            ui.tabBtnSearch.style.background = "#1e293b";
            ui.tabBtnSearch.style.color = "#94a3b8";
        } else {
            ui.tabContentDownload.style.display = "none";
            ui.tabContentSearch.style.display = "block";
            ui.tabBtnSearch.style.background = "#0284c7";
            ui.tabBtnSearch.style.color = "#ffffff";
            ui.tabBtnDownload.style.background = "#1e293b";
            ui.tabBtnDownload.style.color = "#94a3b8";
        }
    }

    function renderVariantChips(inputVal) {
        if (!ui.variantsBox) return;
        const { variants } = generateSearchVariants(inputVal);
        state.generatedVariants = variants;

        if (!variants.length) {
            ui.variantsBox.innerHTML = `<span style="color:#64748b; font-size:10px;">نام فارسی (مثلاً: راستگو یا علی فاضلی راد) را بنویسید...</span>`;
            return;
        }

        ui.variantsBox.innerHTML = "";
        variants.forEach((v, idx) => {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.textContent = v;
            chip.title = "کلیک = پر کردن کادر Patient Name و جستجو در تمام تاریخ‌ها";
            chip.style.cssText = `
                padding: 2px 6px;
                margin: 2px;
                background: ${idx === 0 ? "#0369a1" : "#1e293b"};
                color: ${idx === 0 ? "#fff" : "#bae6fd"};
                border: 1px solid ${idx === 0 ? "#38bdf8" : "#334155"};
                border-radius: 4px;
                font-family: monospace;
                font-size: 10px;
                cursor: pointer;
            `;
            chip.onclick = () => {
                applySearchInCurrentPage(v);
            };
            ui.variantsBox.appendChild(chip);
        });
    }

    function createUI() {
        const oldV12 = document.getElementById("pacs-v12-panel");
        if (oldV12) oldV12.remove();
        if (document.getElementById("pacs-v13-panel")) return;

        const panel = document.createElement("div");
        panel.id = "pacs-v13-panel";
        panel.style.cssText = `
            position: fixed;
            right: 20px;
            bottom: 20px;
            z-index: 2147483647;
            width: 370px;
            padding: 12px;
            background: rgba(15, 23, 42, 0.96);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(56, 189, 248, 0.5);
            border-radius: 12px;
            box-shadow: 0 16px 40px rgba(0,0,0,0.85);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Tahoma, sans-serif;
            font-size: 12px;
            color: #f8fafc;
            direction: rtl;
            user-select: none;
        `;

        // IMPORTANT: Every <button> has explicit type="button" so it NEVER interferes with form submission!
        panel.innerHTML = `
            <div id="pacs-v12-header" style="cursor:move; font-weight:bold; font-size:13px; color:#38bdf8; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
                <span>🎬 مدال پکس (${window.location.hostname.split(".")[0].toUpperCase()})</span>
                <span style="font-size:10px; background:#059669; padding:2px 6px; border-radius:4px; color:#fff; font-weight:normal;">v13.1 Fixed + Cine</span>
            </div>

            <!-- Tab Bar -->
            <div style="display:flex; gap:4px; margin-bottom:8px;">
                <button type="button" id="pacs-v13-tab-dl" style="flex:1; padding:5px; border:none; border-radius:6px; font-size:11px; font-weight:bold; cursor:pointer;">🎬 دانلودر و ویدیو</button>
                <button type="button" id="pacs-v13-tab-search" style="flex:1; padding:5px; border:none; border-radius:6px; font-size:11px; font-weight:bold; cursor:pointer;">🔍 جستجوی فینگلیش و ۳ مرکز</button>
            </div>

            <!-- TAB 1: ORIGINAL v12 DOWNLOADER -->
            <div id="pacs-v13-content-dl">
                <div id="pacs-v12-meta" style="background:rgba(30,41,59,0.7); padding:8px 10px; border-radius:6px; margin-bottom:8px; font-size:11px; border:1px solid rgba(255,255,255,0.06);">
                    در حال شناسایی آزمون...
                </div>

                <button type="button" id="pacs-v13-open-viewer" style="display:none; width:100%; padding:7px; margin-bottom:8px; background:#0284c7; color:#fff; border:none; border-radius:6px; cursor:pointer; font-weight:bold; font-size:11px;">👁️ باز کردن صفحه ویوئر بیمار انتخاب‌شده (View)</button>

                <div style="display:flex; gap:6px; margin-bottom:8px;">
                    <div style="flex:2;">
                        <label style="display:block; font-size:11px; color:#94a3b8; margin-bottom:3px;">انتخاب سری / نما:</label>
                        <select id="pacs-v12-series" style="width:100%; padding:6px 8px; background:#1e293b; color:#f8fafc; border:1px solid #334155; border-radius:6px; font-size:11px; outline:none; direction:ltr; text-align:right;">
                            <option value="">در حال بارگذاری سریها...</option>
                        </select>
                    </div>
                    <div style="flex:1;">
                        <label style="display:block; font-size:11px; color:#94a3b8; margin-bottom:3px;">فرمت خروجی:</label>
                        <select id="pacs-v12-format" style="width:100%; padding:6px 6px; background:#1e293b; color:#38bdf8; font-weight:bold; border:1px solid #0284c7; border-radius:6px; font-size:11px; outline:none; direction:ltr; text-align:center;">
                            <option value="VIDEO" selected>ویدیو (MP4)</option>
                            <option value="DICOM">DICOM (.dcm)</option>
                            <option value="JPEG">JPEG (.jpg)</option>
                        </select>
                    </div>
                </div>

                <!-- Video Options Panel -->
                <div id="pacs-v12-video-opt" style="background:rgba(2, 6, 23, 0.6); padding:8px; border-radius:6px; margin-bottom:8px; border:1px solid rgba(56, 189, 248, 0.2);">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="color:#94a3b8; font-size:11px;">سرعت فریم (FPS):</span>
                        <span id="pacs-v12-fps-val" style="color:#38bdf8; font-family:monospace; font-weight:bold;">20 FPS</span>
                    </div>
                    <input type="range" id="pacs-v12-fps" min="5" max="45" value="20" step="1" style="width:100%; accent-color:#0284c7; margin-bottom:6px; cursor:pointer;">

                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="color:#94a3b8; font-size:11px;">حالت حرکت ویدیو:</span>
                        <select id="pacs-v12-mode" style="background:#1e293b; color:#f8fafc; border:1px solid #334155; border-radius:4px; font-size:10px; padding:2px 4px; outline:none;">
                            <option value="PINGPONG" selected>رفت و برگشت (Cine Loop)</option>
                            <option value="FORWARD">مستقیم (۱ تا آخر)</option>
                        </select>
                    </div>

                    <div style="display:flex; align-items:center; gap:6px;">
                        <input type="checkbox" id="pacs-v12-overlay" checked style="cursor:pointer; accent-color:#0284c7;">
                        <label for="pacs-v12-overlay" style="cursor:pointer; font-size:10px; color:#cbd5e1;">نمایش اطلاعات پزشکی در گوشهها (Medical HUD)</label>
                    </div>
                </div>

                <div style="display:flex; gap:6px; margin-bottom:8px;">
                    <button type="button" id="pacs-v12-start" disabled style="flex:2; padding:9px; background:#059669; color:#fff; border:none; border-radius:6px; cursor:pointer; font-weight:bold; font-size:12px; transition:0.2s;">شروع تولید و دانلود خروجی</button>
                    <button type="button" id="pacs-v12-stop" disabled style="flex:1; padding:9px; background:#dc2626; color:#fff; border:none; border-radius:6px; cursor:pointer; font-size:12px;">توقف</button>
                </div>
            </div>

            <!-- TAB 2: SMART PERSIAN-TO-FINGLISH & MULTI-HOSPITAL SEARCH -->
            <div id="pacs-v13-content-search" style="display:none;">
                <div style="background:rgba(30,41,59,0.75); padding:8px; border-radius:6px; margin-bottom:6px; border:1px solid rgba(56,189,248,0.2);">
                    <label style="display:block; font-size:11px; color:#fcd34d; margin-bottom:3px; font-weight:bold;">نام بیمار (فارسی یا فینگلیش):</label>
                    <input type="text" id="pacs-v13-persian-name" placeholder="مثلاً: راستگو یا علی فاضلی راد" style="width:100%; box-sizing:border-box; padding:6px 8px; background:#0f172a; color:#fff; border:1px solid #0284c7; border-radius:5px; font-size:12px; margin-bottom:5px; outline:none;">
                    <div style="font-size:10px; color:#94a3b8; margin-bottom:3px;">حالت‌های فینگلیش (کلیک روی هر کدام = جستجوی فوری):</div>
                    <div id="pacs-v13-variants" style="min-height:24px; max-height:68px; overflow-y:auto; background:#020617; padding:4px; border-radius:4px; border:1px solid rgba(255,255,255,0.06); direction:ltr; text-align:left;"></div>
                </div>

                <div style="display:flex; gap:5px; margin-bottom:6px;">
                    <div style="flex:1;">
                        <label style="display:block; font-size:10px; color:#94a3b8; margin-bottom:2px;">کد پذیرش (PID):</label>
                        <input type="text" id="pacs-v13-pid" placeholder="PID..." style="width:100%; box-sizing:border-box; padding:5px; background:#1e293b; color:#fff; border:1px solid #334155; border-radius:4px; font-size:11px; direction:ltr;">
                    </div>
                    <div style="flex:1;">
                        <label style="display:block; font-size:10px; color:#94a3b8; margin-bottom:2px;">کد ملی (NID):</label>
                        <input type="text" id="pacs-v13-nid" placeholder="کد ملی..." style="width:100%; box-sizing:border-box; padding:5px; background:#1e293b; color:#fff; border:1px solid #334155; border-radius:4px; font-size:11px; direction:ltr;">
                    </div>
                </div>

                <div style="display:flex; gap:5px; margin-bottom:6px;">
                    <div style="flex:1;">
                        <label style="display:block; font-size:10px; color:#94a3b8; margin-bottom:2px;">مدالیته:</label>
                        <select id="pacs-v13-mod" style="width:100%; padding:5px; background:#1e293b; color:#38bdf8; border:1px solid #334155; border-radius:4px; font-size:11px; direction:ltr;">
                            <option value="ALL">All Modalities</option>
                            <option value="CT">CT</option>
                            <option value="DX">DX (گرافی)</option>
                            <option value="MR">MR (ام‌آر‌آی)</option>
                            <option value="US">US (سونو)</option>
                        </select>
                    </div>
                    <div style="flex:1;">
                        <label style="display:block; font-size:10px; color:#94a3b8; margin-bottom:2px;">بازه زمانی جستجو:</label>
                        <select id="pacs-v13-date-preset" style="width:100%; padding:5px; background:#1e293b; color:#f8fafc; border:1px solid #334155; border-radius:4px; font-size:11px;">
                            <option value="ALL" selected>همه تاریخ‌ها (All Dates)</option>
                            <option value="TODAY">فقط امروز (Today)</option>
                            <option value="YESTERDAY">دیروز (Yesterday)</option>
                            <option value="LASTWEEK">هفته اخیر (Last Week)</option>
                        </select>
                    </div>
                </div>

                <div style="display:flex; gap:5px; margin-bottom:6px;">
                    <button type="button" id="pacs-v13-btn-search-now" style="flex:1; padding:7px; background:#0284c7; color:#fff; border:none; border-radius:5px; font-weight:bold; font-size:11px; cursor:pointer;">🔍 جستجو در همین مرکز</button>
                    <button type="button" id="pacs-v13-btn-probe-all" style="flex:1; padding:7px; background:#059669; color:#fff; border:none; border-radius:5px; font-weight:bold; font-size:11px; cursor:pointer;">🏥 جستجو در هر ۳ بیمارستان</button>
                </div>

                <div id="pacs-v13-multi-results" style="max-height:115px; overflow-y:auto; margin-bottom:6px;"></div>

                <div style="display:flex; justify-content:space-between; align-items:center; padding-top:4px; border-top:1px solid rgba(255,255,255,0.08); margin-bottom:6px;">
                    <label style="display:flex; align-items:center; gap:5px; font-size:10px; color:#cbd5e1; cursor:pointer;">
                        <input type="checkbox" id="pacs-v13-autologin-chk" ${state.autoLoginEnabled ? "checked" : ""} style="accent-color:#059669; cursor:pointer;">
                        ورود خودکار (doc / doc)
                    </label>
                    <button type="button" id="pacs-v13-btn-export-schema" style="padding:3px 6px; background:#334155; color:#94a3b8; border:1px solid #475569; border-radius:4px; font-size:9px; cursor:pointer;">🤖 خروجی ساختار</button>
                </div>
            </div>

            <!-- Shared Progress & Log Footer -->
            <div style="display:flex; justify-content:space-between; font-size:11px; margin-bottom:4px;">
                <span id="pacs-v12-status" style="color:#94a3b8;">آماده به کار</span>
                <span id="pacs-v12-pct" style="color:#38bdf8; font-family:monospace; font-weight:bold;">0%</span>
            </div>
            <progress id="pacs-v12-prog" value="0" max="1" style="width:100%; height:6px; margin-bottom:8px; border-radius:3px; accent-color:#0284c7;"></progress>
            <div id="pacs-v12-log" style="height:68px; overflow-y:auto; background:#020617; border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:6px; font-family:monospace; font-size:10px; direction:ltr; text-align:left;"></div>
        `;

        document.body.appendChild(panel);

        ui.panel = panel;
        ui.metaBox = panel.querySelector("#pacs-v12-meta");
        ui.openViewerBtn = panel.querySelector("#pacs-v13-open-viewer");
        ui.seriesSelect = panel.querySelector("#pacs-v12-series");
        ui.formatSelect = panel.querySelector("#pacs-v12-format");
        ui.videoOptionsBox = panel.querySelector("#pacs-v12-video-opt");
        ui.fpsInput = panel.querySelector("#pacs-v12-fps");
        ui.fpsValDisplay = panel.querySelector("#pacs-v12-fps-val");
        ui.modeSelect = panel.querySelector("#pacs-v12-mode");
        ui.overlayCheckbox = panel.querySelector("#pacs-v12-overlay");
        ui.startBtn = panel.querySelector("#pacs-v12-start");
        ui.stopBtn = panel.querySelector("#pacs-v12-stop");
        ui.progressBar = panel.querySelector("#pacs-v12-prog");
        ui.percentText = panel.querySelector("#pacs-v12-pct");
        ui.statusText = panel.querySelector("#pacs-v12-status");
        ui.logBox = panel.querySelector("#pacs-v12-log");

        // v13.1 elements
        ui.tabBtnDownload = panel.querySelector("#pacs-v13-tab-dl");
        ui.tabBtnSearch = panel.querySelector("#pacs-v13-tab-search");
        ui.tabContentDownload = panel.querySelector("#pacs-v13-content-dl");
        ui.tabContentSearch = panel.querySelector("#pacs-v13-content-search");
        ui.persianInput = panel.querySelector("#pacs-v13-persian-name");
        ui.variantsBox = panel.querySelector("#pacs-v13-variants");
        ui.pidInput = panel.querySelector("#pacs-v13-pid");
        ui.nidInput = panel.querySelector("#pacs-v13-nid");
        ui.modalitySelect = panel.querySelector("#pacs-v13-mod");
        ui.datePresetSelect = panel.querySelector("#pacs-v13-date-preset");
        ui.multiResultsBox = panel.querySelector("#pacs-v13-multi-results");
        ui.autoLoginCheckbox = panel.querySelector("#pacs-v13-autologin-chk");

        // Restore persisted values into inputs
        if (state.searchQueryPersian) ui.persianInput.value = state.searchQueryPersian;
        if (state.searchPid) ui.pidInput.value = state.searchPid;
        if (state.searchNid) ui.nidInput.value = state.searchNid;
        if (state.searchModality) ui.modalitySelect.value = state.searchModality;
        if (state.searchDatePreset) ui.datePresetSelect.value = state.searchDatePreset;

        ui.tabBtnDownload.onclick = () => switchTab("DOWNLOAD");
        ui.tabBtnSearch.onclick = () => switchTab("SEARCH");

        ui.openViewerBtn.onclick = () => triggerDefaultPageView();
        ui.startBtn.onclick = startDownload;
        ui.stopBtn.onclick = () => { stopRequested = true; };

        ui.seriesSelect.onchange = function () {
            state.selectedSeriesKey = this.value;
            refreshUIState();
        };

        ui.formatSelect.onchange = function () {
            state.outputFormat = this.value;
            refreshUIState();
        };

        ui.fpsInput.oninput = function () {
            state.fps = parseInt(this.value, 10);
            ui.fpsValDisplay.textContent = `${state.fps} FPS`;
        };

        ui.modeSelect.onchange = function () {
            state.playMode = this.value;
        };

        ui.overlayCheckbox.onchange = function () {
            state.includeOverlay = this.checked;
        };

        ui.persianInput.oninput = function () {
            state.searchQueryPersian = this.value;
            renderVariantChips(this.value);
        };

        ui.persianInput.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                e.stopPropagation();
                const { primary } = generateSearchVariants(this.value);
                applySearchInCurrentPage(primary);
            }
        });

        ui.pidInput.oninput = function () { state.searchPid = this.value; };
        ui.nidInput.oninput = function () { state.searchNid = this.value; };
        ui.modalitySelect.onchange = function () { state.searchModality = this.value; };
        ui.datePresetSelect.onchange = function () { state.searchDatePreset = this.value; };

        panel.querySelector("#pacs-v13-btn-search-now").onclick = () => {
            const { primary } = generateSearchVariants(ui.persianInput.value);
            applySearchInCurrentPage(primary);
        };

        panel.querySelector("#pacs-v13-btn-probe-all").onclick = () => {
            searchAcrossAllThreeHospitals();
        };

        panel.querySelector("#pacs-v13-btn-export-schema").onclick = exportBotTechnicalSchema;

        ui.autoLoginCheckbox.onchange = function () {
            state.autoLoginEnabled = this.checked;
            localStorage.setItem("pacs_v13_autologin", this.checked ? "1" : "0");
            log(`ورود خودکار (doc/doc): ${this.checked ? "فعال" : "غیرفعال"}`, "info");
        };

        // Track row clicks in Default.aspx
        if (isSearchPage) {
            document.addEventListener("click", (e) => {
                const tr = e.target?.closest?.('tr[onclick*="OnSelect"]');
                if (tr) {
                    const tds = Array.from(tr.querySelectorAll("td"));
                    state.selectedRowOnDefault = {
                        pid: (tds[1]?.textContent || "").trim(),
                        name: (tds[2]?.textContent || "").trim(),
                        modality: (tds[8]?.textContent || "").trim()
                    };
                    setTimeout(refreshUIState, 150);
                }
            });
        }

        const header = panel.querySelector("#pacs-v12-header");
        let isDragging = false, startX, startY, initialX, initialY;

        header.onmousedown = function (e) {
            isDragging = true;
            startX = e.clientX;
            startY = e.clientY;
            const rect = panel.getBoundingClientRect();
            initialX = rect.left;
            initialY = rect.top;
            document.onmousemove = function (e) {
                if (!isDragging) return;
                panel.style.left = `${initialX + (e.clientX - startX)}px`;
                panel.style.top = `${initialY + (e.clientY - startY)}px`;
                panel.style.right = "auto";
                panel.style.bottom = "auto";
            };
            document.onmouseup = function () {
                isDragging = false;
                document.onmousemove = null;
                document.onmouseup = null;
            };
        };

        window.addEventListener("click", () => setTimeout(refreshUIState, 200));
        window.addEventListener("wheel", () => setTimeout(refreshUIState, 200), { passive: true });

        renderVariantChips(state.searchQueryPersian);
        switchTab(state.activeTab);
        setInterval(refreshUIState, 1000);
        refreshUIState();
        checkAndPerformAutoLogin();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", createUI);
    } else {
        createUI();
    }
})();
