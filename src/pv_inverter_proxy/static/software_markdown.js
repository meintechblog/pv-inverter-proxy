/* software_markdown.js — Phase 46 Plan 03 — D-28, D-29, D-30
 *
 * Allow-list Markdown renderer for untrusted GitHub release notes.
 *
 * SECURITY CONTRACT (T-46-06 mitigation):
 *   - Pure DOM emission via document.createElement + textContent
 *   - NEVER uses string-HTML sinks (see D-30 forbidden list)
 *   - No support for links, images, raw HTML, iframes, tables, code fences,
 *     nested lists, or blockquotes — all fall through as literal text nodes.
 *   - Unclosed inline tokens (`**`, `*`, `` ` ``) fall through as literal text
 *     (Pitfall 8 in 46-RESEARCH.md).
 *
 * Allow-list (D-28):
 *   - `# H1`, `## H2`, `### H3` (single # + space prefix, per line)
 *   - `**bold**`, `*italic*`, `` `code` `` inline
 *   - `- item` or `* item` flat bullet list
 *   - blank line terminates paragraphs / lists
 *   - plain line -> paragraph text via textContent
 *
 * Forbidden (D-29) — ALL fall through as literal text:
 *   - Raw HTML tags
 *   - Markdown links [text](url) and images ![alt](url)
 *   - Code fences, tables, nested lists, blockquotes
 *   - HTML entities beyond browser default text-node handling
 *   - `javascript:` / `data:` / `vbscript:` URIs (no links at all)
 */
(function () {
  'use strict';

  /**
   * Walk `text` emitting textNodes and allow-listed inline elements into `parent`.
   * Uses a single regex with alternation so unclosed tokens naturally fall through.
   * @param {string} text
   * @param {Node} parent
   */
  function renderInline(text, parent) {
    if (typeof text !== 'string' || text.length === 0) return;
    // Order matters: `**bold**` must match before `*italic*`.
    var pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
    var lastIndex = 0;
    var match;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parent.appendChild(
          document.createTextNode(text.slice(lastIndex, match.index))
        );
      }
      var token = match[0];
      var el;
      if (token.indexOf('**') === 0) {
        el = document.createElement('strong');
        el.textContent = token.slice(2, -2);
      } else if (token.charAt(0) === '`') {
        el = document.createElement('code');
        el.textContent = token.slice(1, -1);
      } else {
        el = document.createElement('em');
        el.textContent = token.slice(1, -1);
      }
      parent.appendChild(el);
      lastIndex = pattern.lastIndex;
    }
    if (lastIndex < text.length) {
      parent.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
  }

  /**
   * Clear `targetEl` and append DOM nodes built from the allow-listed subset
   * of Markdown in `source`. No attribute injection, no string-HTML sinks.
   * @param {string} source
   * @param {HTMLElement} targetEl
   */
  function renderSoftwareMarkdown(source, targetEl) {
    if (!targetEl) return;
    // Clear via textContent — safe, no side-effects on existing children.
    targetEl.textContent = '';
    if (typeof source !== 'string' || source.length === 0) return;

    var lines = source.split('\n');
    var currentParagraph = null;
    var currentList = null;

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      // Order matters: check most-specific heading prefix first (### before ## before #).
      if (/^###\s+/.test(line)) {
        currentParagraph = null;
        currentList = null;
        var h3 = document.createElement('h5');
        h3.className = 've-md-h3';
        h3.textContent = line.replace(/^###\s+/, '');
        targetEl.appendChild(h3);
      } else if (/^##\s+/.test(line)) {
        currentParagraph = null;
        currentList = null;
        var h2 = document.createElement('h4');
        h2.className = 've-md-h2';
        h2.textContent = line.replace(/^##\s+/, '');
        targetEl.appendChild(h2);
      } else if (/^#\s+/.test(line)) {
        currentParagraph = null;
        currentList = null;
        var h1 = document.createElement('h3');
        h1.className = 've-md-h1';
        h1.textContent = line.replace(/^#\s+/, '');
        targetEl.appendChild(h1);
      } else if (/^[-*]\s+/.test(line)) {
        currentParagraph = null;
        if (!currentList) {
          currentList = document.createElement('ul');
          currentList.className = 've-md-list';
          targetEl.appendChild(currentList);
        }
        var li = document.createElement('li');
        renderInline(line.replace(/^[-*]\s+/, ''), li);
        currentList.appendChild(li);
      } else if (line.trim() === '') {
        currentParagraph = null;
        currentList = null;
      } else {
        currentList = null;
        if (!currentParagraph) {
          currentParagraph = document.createElement('p');
          currentParagraph.className = 've-md-p';
          targetEl.appendChild(currentParagraph);
        } else {
          // Soft-wrap inside a paragraph: use <br> (safe element, no attributes).
          currentParagraph.appendChild(document.createElement('br'));
        }
        renderInline(line, currentParagraph);
      }
    }
  }

  window.renderSoftwareMarkdown = renderSoftwareMarkdown;
})();
