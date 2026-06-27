const DEFAULT_EMOJIS = [
  { emoji: ":)", label: "smile", group: "Classic" },
  { emoji: ":D", label: "big grin", group: "Classic" },
  { emoji: ";)", label: "wink", group: "Classic" },
  { emoji: ":P", label: "tongue out", group: "Classic" },
  { emoji: "XD", label: "laughing eyes closed", group: "Classic" },
  { emoji: ":(", label: "sad", group: "Classic" },
  { emoji: "<3", label: "heart", group: "Classic" },
  { emoji: "😀", label: "grinning face", group: "Smileys" },
  { emoji: "😂", label: "face with tears of joy", group: "Smileys" },
  { emoji: "😊", label: "smiling face with smiling eyes", group: "Smileys" },
  { emoji: "😉", label: "winking face", group: "Smileys" },
  { emoji: "😍", label: "smiling face with heart-eyes", group: "Smileys" },
  { emoji: "😎", label: "smiling face with sunglasses", group: "Smileys" },
  { emoji: "👍", label: "thumbs up", group: "People" },
  { emoji: "🙏", label: "folded hands", group: "People" },
  { emoji: "❤️", label: "red heart", group: "Hearts" },
  { emoji: "🔥", label: "fire", group: "Objects" },
  { emoji: "🎉", label: "party popper", group: "Objects" }
];

class EchoChatEmojiPicker extends HTMLElement {
  static get observedAttributes() { return ["data-source"]; }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._items = [...DEFAULT_EMOJIS];
    this._query = "";
    this._group = "All";
    this._loadId = 0;
  }

  connectedCallback() {
    this.render();
    void this.loadData();
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (name === "data-source" && oldValue !== newValue && this.isConnected) {
      void this.loadData();
    }
  }

  async loadData() {
    const dataSource = String(this.getAttribute("data-source") || "").trim();
    const loadId = ++this._loadId;
    if (!dataSource) {
      this._items = [...DEFAULT_EMOJIS];
      this.render();
      return;
    }
    try {
      const res = await fetch(dataSource, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (loadId !== this._loadId) return;
      if (Array.isArray(data) && data.length) {
        this._items = data
          .map((item) => ({
            emoji: String(item?.emoji || item?.unicode || item?.native || "").trim(),
            label: String(item?.label || item?.annotation || item?.name || "").trim(),
            group: String(item?.group || item?.category || "Other").trim() || "Other"
          }))
          .filter((item) => item.emoji);
      } else {
        this._items = [...DEFAULT_EMOJIS];
      }
      this.render();
    } catch (err) {
      console.warn("[emoji-picker] failed to load local emoji data", err);
      this._items = [...DEFAULT_EMOJIS];
      this.render();
    }
  }

  get groups() {
    const seen = new Set();
    const groups = ["All"];
    for (const item of this._items) {
      const group = String(item.group || "Other");
      if (!seen.has(group)) {
        seen.add(group);
        groups.push(group);
      }
    }
    return groups;
  }

  get filteredItems() {
    const q = this._query.trim().toLowerCase();
    return this._items.filter((item) => {
      if (this._group !== "All" && item.group !== this._group) return false;
      if (!q) return true;
      return item.emoji.toLowerCase().includes(q) || String(item.label || "").toLowerCase().includes(q);
    });
  }

  _onSearchInput = (event) => {
    this._query = String(event?.target?.value || "");
    this.render();
  };

  _setGroup(group) {
    this._group = group;
    this.render();
  }

  _pick(item) {
    const value = String(item?.emoji || "");
    if (!value) return;
    this.dispatchEvent(new CustomEvent("emoji-click", {
      detail: {
        unicode: value,
        emoji: {
          unicode: value,
          native: value,
          emoji: value,
          name: String(item?.label || "")
        }
      },
      bubbles: true,
      composed: true
    }));
  }

  render() {
    const items = this.filteredItems;
    const groups = this.groups;
    const groupButtons = groups.map((group) => `
      <button class="tab ${group === this._group ? "active" : ""}" type="button" data-group="${escapeHtml(group)}">${escapeHtml(group)}</button>
    `).join("");
    const itemButtons = items.map((item) => `
      <button class="emojiBtn" type="button" data-emoji="${escapeHtml(item.emoji)}" aria-label="${escapeHtml(item.label || item.emoji)}" title="${escapeHtml(item.label || item.emoji)}">
        <span class="emojiGlyph">${escapeHtml(item.emoji)}</span>
      </button>
    `).join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          height: 100%;
          box-sizing: border-box;
          font-family: Arial, Helvetica, sans-serif;
          color: #111827;
        }
        *, *::before, *::after { box-sizing: border-box; }
        .wrap {
          display: flex;
          flex-direction: column;
          width: 100%;
          height: 100%;
          background: linear-gradient(180deg, #fffdf8 0%, #f7f1dc 100%);
        }
        .toolbar {
          padding: 10px;
          border-bottom: 1px solid rgba(0,0,0,0.12);
          background: rgba(255,255,255,0.92);
        }
        .search {
          width: 100%;
          padding: 8px 10px;
          border-radius: 8px;
          border: 1px solid #c8b57a;
          background: #fffdf7;
          font-size: 13px;
          outline: none;
        }
        .tabs {
          display: flex;
          gap: 6px;
          padding: 8px 10px;
          overflow-x: auto;
          border-bottom: 1px solid rgba(0,0,0,0.1);
          background: rgba(255,255,255,0.78);
        }
        .tab {
          border: 1px solid #c8b57a;
          background: #fff7d6;
          border-radius: 999px;
          padding: 5px 10px;
          cursor: pointer;
          white-space: nowrap;
          font-size: 12px;
        }
        .tab.active {
          background: linear-gradient(180deg, #f7d86f 0%, #e2b94a 100%);
          border-color: #8a6921;
          color: #2f2407;
          font-weight: 700;
        }
        .grid {
          flex: 1;
          overflow: auto;
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(42px, 1fr));
          gap: 8px;
          padding: 10px;
          align-content: start;
        }
        .emojiBtn {
          min-height: 40px;
          border: 1px solid #d6c38f;
          border-radius: 10px;
          background: #fffdf7;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          transition: transform 0.08s ease, background 0.12s ease, border-color 0.12s ease;
        }
        .emojiBtn:hover {
          background: #fff2bf;
          border-color: #b68a2b;
          transform: translateY(-1px);
        }
        .emojiGlyph {
          font-size: 22px;
          line-height: 1;
        }
        .empty {
          padding: 18px 14px;
          color: #6b7280;
          font-size: 13px;
        }
      </style>
      <div class="wrap">
        <div class="toolbar">
          <input class="search" type="search" placeholder="Search emoticons" value="${escapeHtml(this._query)}" />
        </div>
        <div class="tabs">${groupButtons}</div>
        <div class="grid">${itemButtons || '<div class="empty">No emoticons found.</div>'}</div>
      </div>
    `;

    const search = this.shadowRoot.querySelector('.search');
    if (search) search.addEventListener('input', this._onSearchInput);

    this.shadowRoot.querySelectorAll('.tab').forEach((btn) => {
      btn.addEventListener('click', () => this._setGroup(String(btn.getAttribute('data-group') || 'All')));
    });

    this.shadowRoot.querySelectorAll('.emojiBtn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const emoji = String(btn.getAttribute('data-emoji') || '');
        const item = this._items.find((entry) => entry.emoji === emoji) || { emoji, label: emoji };
        this._pick(item);
      });
    });
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

if (!window.customElements?.get?.("emoji-picker")) {
  window.customElements.define("emoji-picker", EchoChatEmojiPicker);
}
