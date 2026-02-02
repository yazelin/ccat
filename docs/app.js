(function () {
  const CATLIST_URL = "https://raw.githubusercontent.com/yazelin/catime/main/catlist.json";
  const PAGE_SIZE = 20;

  let allCats = [];
  let filtered = [];
  let loaded = 0;
  let loading = false;
  let selectedDate = ""; // "YYYY-MM-DD" or ""

  const gallery = document.getElementById("gallery");
  const endMsg = document.getElementById("end-msg");
  const modelSelect = document.getElementById("model-filter");
  const timelineList = document.getElementById("timeline-list");
  const timelineNav = document.getElementById("timeline");
  const timelineToggle = document.getElementById("timeline-toggle");
  const lightbox = document.getElementById("lightbox");
  const lbImg = document.getElementById("lb-img");
  const lbInfo = document.getElementById("lb-info");
  const lbClose = document.getElementById("lb-close");
  const lbPrompt = document.getElementById("lb-prompt");
  const lbPromptText = document.getElementById("lb-prompt-text");
  const lbCopyBtn = document.getElementById("lb-copy-btn");

  // Date picker elements
  const datePickerBtn = document.getElementById("date-picker-btn");
  const dateDropdown = document.getElementById("date-dropdown");
  const ddPrev = document.getElementById("dd-prev");
  const ddNext = document.getElementById("dd-next");
  const ddMonthLabel = document.getElementById("dd-month-label");
  const ddDays = document.getElementById("dd-days");
  const ddClear = document.getElementById("dd-clear");

  let calYear = new Date().getFullYear();
  let calMonth = new Date().getMonth();
  let catDates = new Set();

  // Fetch data
  fetch(CATLIST_URL)
    .then(r => r.json())
    .then(data => {
      allCats = data.filter(c => c.status !== "failed").reverse();
      allCats.forEach(c => catDates.add(c.timestamp.split(" ")[0]));
      populateModels();
      buildTimeline();
      // Init calendar to latest cat's month
      if (allCats.length) {
        const parts = allCats[0].timestamp.split(" ")[0].split("-");
        calYear = parseInt(parts[0], 10);
        calMonth = parseInt(parts[1], 10) - 1;
      }
      applyFilter();
    })
    .catch(err => {
      gallery.innerHTML = `<p style="padding:2rem;color:var(--pink)">Failed to load cat list: ${err.message}</p>`;
    });

  function populateModels() {
    const models = [...new Set(allCats.map(c => c.model).filter(Boolean))].sort();
    models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m; opt.textContent = m;
      modelSelect.appendChild(opt);
    });
  }

  function buildTimeline() {
    const map = {};
    allCats.forEach(c => {
      const [date] = c.timestamp.split(" ");
      const [y, m] = date.split("-");
      if (!map[y]) map[y] = new Set();
      map[y].add(m);
    });
    let html = "";
    Object.keys(map).sort().reverse().forEach(y => {
      html += `<div class="year">${y}</div>`;
      [...map[y]].sort().reverse().forEach(m => {
        html += `<a href="#" data-ym="${y}-${m}">${y}-${m}</a>`;
      });
    });
    timelineList.innerHTML = html;
  }

  // ── Date picker ──
  datePickerBtn.addEventListener("click", e => {
    e.stopPropagation();
    dateDropdown.classList.toggle("hidden");
    if (!dateDropdown.classList.contains("hidden")) renderCalendar();
  });
  document.addEventListener("click", e => {
    if (!dateDropdown.classList.contains("hidden") && !document.getElementById("date-picker").contains(e.target)) {
      dateDropdown.classList.add("hidden");
    }
  });
  ddPrev.addEventListener("click", () => { calMonth--; if (calMonth < 0) { calMonth = 11; calYear--; } renderCalendar(); });
  ddNext.addEventListener("click", () => { calMonth++; if (calMonth > 11) { calMonth = 0; calYear++; } renderCalendar(); });
  ddClear.addEventListener("click", () => {
    selectedDate = "";
    datePickerBtn.textContent = "\u{1f4c5} All Dates";
    datePickerBtn.classList.remove("active");
    dateDropdown.classList.add("hidden");
    applyFilter();
  });

  function renderCalendar() {
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    ddMonthLabel.textContent = `${months[calMonth]} ${calYear}`;
    const first = new Date(calYear, calMonth, 1);
    const startDay = first.getDay();
    const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
    const todayStr = new Date().toISOString().slice(0, 10);

    let html = "";
    // Empty cells before first day
    for (let i = 0; i < startDay; i++) html += `<button class="other-month" disabled></button>`;
    for (let d = 1; d <= daysInMonth; d++) {
      const ds = `${calYear}-${String(calMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const cls = [];
      if (ds === todayStr) cls.push("today");
      if (ds === selectedDate) cls.push("selected");
      if (catDates.has(ds)) cls.push("has-cat");
      html += `<button data-date="${ds}" class="${cls.join(" ")}">${d}</button>`;
    }
    ddDays.innerHTML = html;
  }

  ddDays.addEventListener("click", e => {
    const date = e.target.dataset.date;
    if (!date) return;
    selectedDate = date;
    datePickerBtn.textContent = "\u{1f4c5} " + date;
    datePickerBtn.classList.add("active");
    dateDropdown.classList.add("hidden");
    applyFilter();
  });

  // ── Filter ──
  function applyFilter() {
    const model = modelSelect.value;
    filtered = allCats.filter(c => {
      if (model && c.model !== model) return false;
      if (selectedDate && !c.timestamp.startsWith(selectedDate)) return false;
      return true;
    });
    loaded = 0;
    gallery.innerHTML = "";
    endMsg.classList.add("loading");
    endMsg.classList.remove("hidden");
    loadMore();
  }

  modelSelect.addEventListener("change", applyFilter);

  // ── Render cards ──
  function loadMore() {
    if (loading || loaded >= filtered.length) return;
    loading = true;
    const slice = filtered.slice(loaded, loaded + PAGE_SIZE);
    let lastMonth = "";
    if (loaded > 0) {
      const prev = filtered[loaded - 1];
      lastMonth = prev.timestamp.slice(0, 7);
    }
    const frag = document.createDocumentFragment();
    slice.forEach(cat => {
      const month = cat.timestamp.slice(0, 7);
      if (month !== lastMonth) {
        const sep = document.createElement("div");
        sep.className = "month-sep";
        sep.id = `m-${month}`;
        sep.textContent = month;
        frag.appendChild(sep);
        lastMonth = month;
      }
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <img src="${cat.url}" alt="Cat #${cat.number}" loading="lazy">
        <div class="card-info">
          <div class="time">#${cat.number} &middot; ${cat.timestamp}</div>
          ${cat.model ? `<span class="model">${cat.model}</span>` : ""}
        </div>`;
      card.addEventListener("click", () => openLightbox(cat));
      frag.appendChild(card);
    });
    gallery.appendChild(frag);
    loaded += slice.length;
    loading = false;
    if (loaded >= filtered.length) {
      endMsg.classList.remove("loading");
    }
  }

  // ── Infinite scroll ──
  const observer = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) loadMore();
  }, { rootMargin: "400px" });
  observer.observe(endMsg);

  // ── Timeline click ──
  timelineList.addEventListener("click", e => {
    e.preventDefault();
    const ym = e.target.dataset.ym;
    if (!ym) return;
    const idx = filtered.findIndex(c => c.timestamp.startsWith(ym));
    if (idx === -1) return;
    while (loaded <= idx && loaded < filtered.length) loadMore();
    const el = document.getElementById(`m-${ym}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    if (window.innerWidth <= 1024) timelineNav.classList.remove("open");
  });

  timelineToggle.addEventListener("click", () => timelineNav.classList.toggle("open"));

  // ── Lightbox ──
  function openLightbox(cat) {
    lbImg.src = cat.url;
    lbInfo.textContent = `#${cat.number} \u00b7 ${cat.timestamp} \u00b7 ${cat.model || ""}`;
    if (cat.prompt) {
      lbPromptText.textContent = cat.prompt;
      lbPrompt.classList.remove("hidden");
      lbCopyBtn.textContent = "\u{1f4cb} Copy";
    } else {
      lbPrompt.classList.add("hidden");
    }
    lightbox.classList.remove("hidden");
  }
  lbCopyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(lbPromptText.textContent).then(() => {
      lbCopyBtn.textContent = "\u2705 Copied!";
      setTimeout(() => { lbCopyBtn.textContent = "\u{1f4cb} Copy"; }, 1500);
    });
  });
  lbClose.addEventListener("click", () => lightbox.classList.add("hidden"));
  lightbox.addEventListener("click", e => { if (e.target === lightbox) lightbox.classList.add("hidden"); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") lightbox.classList.add("hidden"); });

})();
