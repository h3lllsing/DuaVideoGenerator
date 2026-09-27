(function () {
  'use strict';

  var API = 'http://127.0.0.1:7871/api/v1';
  var PLATFORMS = ['tiktok', 'instagram', 'facebook'];
  var PLATFORM_LABEL = { tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook' };
  var GLYPH = { done: '✅', wait: '⏳', fail: '❌', busy: '🔒', warn: '⚠️', info: 'ℹ️' };
  var POLL_MS = 2000;

  var state = {
    duas: [],
    ledger: {},
    quota: null,
    busy: {},
    selected: null,
    filter: '',
    liveMode: false,
    inFlight: {},
    poll: null,
    open: false
  };

  function el(id) { return document.getElementById(id); }

  function esc(v) {
    return String(v == null ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function request(method, path) {
    return fetch(API + path, { method: method, headers: { 'Content-Type': 'application/json' } })
      .then(function (res) {
        return res.text().then(function (txt) {
          var body;
          try { body = txt ? JSON.parse(txt) : {}; } catch (e) { body = { error: txt }; }
          return { status: res.status, ok: res.ok, body: body };
        });
      });
  }

  function errorText(r) {
    var b = r.body || {};
    return b.error || b.message || b.note || ('HTTP ' + r.status);
  }

  function platformRecord(duaId, platform) {
    var entry = state.ledger[duaId];
    if (!entry || typeof entry !== 'object') return null;
    var rec = entry[platform];
    if (rec && typeof rec === 'object') return rec;
    return null;
  }

  function legacyCompleted(entry) {
    if (!entry || typeof entry !== 'object') return false;
    if (entry.status === 'uploaded' || entry.phase === 'completed') return true;
    return false;
  }

  function isLocked(duaId, platform) {
    var list = state.busy;
    if (!Array.isArray(list)) return false;
    return list.indexOf(platform + ':' + duaId) >= 0;
  }

  function dryFlag() { return state.liveMode ? '' : '1'; }

  function loadDuas() {
    return request('GET', '/duas').then(function (r) {
      if (r.status === 200 && r.body && Array.isArray(r.body.duas)) {
        state.duas = r.body.duas;
      } else if (Array.isArray(r.body)) {
        state.duas = r.body;
      }
      renderPicker();
    }).catch(function (e) { setBanner(GLYPH.fail + ' duas load nahi hue: ' + e.message, 'no'); });
  }

  function loadStatus() {
    return request('GET', '/upload/status').then(function (r) {
      if (r.status === 200 && r.body) {
        state.ledger = (r.body.duas && typeof r.body.duas === 'object') ? r.body.duas : {};
      }
      renderRows();
    }).catch(function () { /* transient */ });
  }

  function loadQuota() {
    return request('GET', '/upload/quota').then(function (r) {
      if (r.status === 200 && r.body) state.quota = r.body.quota || null;
      renderQuota();
    }).catch(function () { renderQuota(); });
  }

  function loadBusy() {
    return request('GET', '/upload/busy').then(function (r) {
      if (r.status === 200 && r.body) state.busy = r.body.in_flight || [];
      renderRows();
    }).catch(function () { /* transient */ });
  }

  function setBanner(msg, cls) {
    var b = el('social_banner');
    if (!b) return;
    b.textContent = msg;
    b.className = 'aihint ' + (cls || '');
  }

  function filteredDuas() {
    var q = state.filter.trim().toLowerCase();
    if (!q) return state.duas;
    return state.duas.filter(function (d) {
      return String(d.title || '').toLowerCase().indexOf(q) >= 0
        || String(d.id || '').toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderPicker() {
    var sel = el('social_picker');
    if (!sel) return;
    var list = filteredDuas();
    var opts = ['<option value="">-- dua chunein --</option>'];
    list.slice(0, 500).forEach(function (d) {
      opts.push('<option value="' + esc(d.id) + '"' + (d.id === state.selected ? ' selected' : '') + '>')
        ;
      opts[opts.length - 1] += esc(d.title || d.id) + '</option>';
    });
    sel.innerHTML = opts.join('');
  }

  function statusCell(duaId, platform) {
    var rec = platformRecord(duaId, platform);
    if (rec) {
      if (rec.phase === 'completed' || rec.status === GLYPH.done) {
        var url = rec.url || (rec.platform_id ? 'https://' + platform + '.com/' + rec.platform_id : '');
        return { glyph: GLYPH.done, text: 'Uploaded', url: url, error: '' };
      }
      if (rec.phase === 'running' || rec.phase === 'uploading') {
        return { glyph: GLYPH.wait, text: 'In progress', url: '', error: '' };
      }
      if (rec.error) {
        return { glyph: GLYPH.fail, text: 'Failed', url: '', error: String(rec.error) };
      }
      return { glyph: GLYPH.wait, text: 'Pending', url: '', error: '' };
    }
    if (platform === 'youtube' && legacyCompleted(state.ledger[duaId])) {
      return { glyph: GLYPH.done, text: 'Uploaded', url: '', error: '' };
    }
    return { glyph: GLYPH.wait, text: 'Pending', url: '', error: '' };
  }

  function renderRows() {
    var host = el('social_rows');
    if (!host) return;
    if (!state.selected) {
      host.innerHTML = '<div class="aihint">Pehle ek dua chunein.</div>';
      return;
    }
    var html = PLATFORMS.map(function (p) {
      var st = statusCell(state.selected, p);
      var flying = !!state.inFlight[p];
      var locked = isLocked(state.selected, p);
      var disabled = flying || locked;
      var btnLabel = flying ? 'Running...' : (st.glyph === GLYPH.done ? 'Retry' : 'Upload');
      var glyph = flying ? GLYPH.wait : (locked ? GLYPH.busy : st.glyph);
      var detail = '';
      if (st.error) detail = '<div class="aihint no">' + esc(st.error) + '</div>';
      else if (st.url) detail = '<div class="aihint ok"><a href="' + esc(st.url) + '" target="_blank" rel="noopener">' + esc(st.url) + '</a></div>';
      return ''
        + '<div class="panel-section" data-platform="' + p + '">'
        + '  <div class="yt-form-row">'
        + '    <div style="flex:1"><strong>' + glyph + ' ' + esc(PLATFORM_LABEL[p]) + '</strong> &mdash; ' + esc(st.text) + '</div>'
        + '    <button class="btn-sm" data-act="upload" data-platform="' + p + '"' + (disabled ? ' disabled' : '') + '>' + esc(btnLabel) + '</button>'
        + '  </div>'
        + detail
        + '</div>';
    }).join('');

    html += ''
      + '<div class="panel-section">'
      + '  <button class="btn-sm" data-act="all">' + (state.liveMode ? '&#9888; Upload ALL (live)' : '&#9654; Upload ALL (dry run)') + '</button>'
      + '</div>';

    host.innerHTML = html;
  }

  function renderQuota() {
    var host = el('social_quota');
    if (!host) return;
    var q = state.quota;
    if (!q) {
      host.innerHTML = '<div class="aihint">Quota load nahi hua.</div>';
      return;
    }
    var used = q.used || 0;
    var ceiling = q.ceiling || 0;
    var remaining = q.remaining == null ? 0 : q.remaining;
    var day = q.date || '';
    host.innerHTML = ''
      + '<div class="yt-stat-bar">'
      + '  <div class="statnum">YouTube daily quota: ' + used + ' / ' + ceiling + ' used &middot; ' + remaining + ' remaining</div>'
      + '</div>'
      + '<div class="aihint">Units ' + (q.units_spent_today || 0) + ' / ' + (q.daily_budget || 0)
      + ' &middot; ceiling ' + ceiling + ' &middot; ' + esc(day) + '</div>'
      + '<div class="aihint">Ye quota sirf YouTube ke liye hai. TikTok, Instagram aur Facebook ko ye limit nahi karta.</div>';
  }

  function dryLabel(one, good) {
    if (!good) return 'failed';
    return (one && one.dry_run === true) ? 'dry-run OK (kuch upload nahi hua)' : 'uploaded';
  }

  function renderPartial(results) {
    var host = el('social_partial');
    if (!host) return;
    var rows = PLATFORMS.map(function (p) {
      var one = (results && results[p]) || {};
      var good = one.ok === true || one.status === GLYPH.done || !!one.url;
      var glyph = typeof one.status === 'string' && one.status ? one.status : (good ? GLYPH.done : GLYPH.fail);
      var line = good
        ? (one.url ? '<a href="' + esc(one.url) + '" target="_blank" rel="noopener">' + esc(one.url) + '</a>' : esc(dryLabel(one, true)))
        : esc(one.message || one.error || one.failure || 'failed');
      return ''
        + '<div class="yt-form-row">'
        + '  <div style="flex:1"><strong>' + glyph + ' ' + esc(PLATFORM_LABEL[p]) + '</strong> &mdash; ' + line + '</div>'
        + '</div>';
    }).join('');
    host.innerHTML = ''
      + '<div class="panel-section">'
      + '  <div class="panel-section-title">Partial result (per platform)</div>'
      + rows
      + '</div>';
  }

  function renderMode() {
    var b = el('social_mode');
    if (!b) return;
    b.textContent = state.liveMode ? 'LIVE mode - asli upload hoga' : 'DRY RUN mode';
    b.className = state.liveMode ? 'aihint no' : 'aihint ok';
    var t = el('social_modebtn');
    if (t) t.textContent = state.liveMode ? 'Disable live upload' : 'Enable live upload';
  }

  function renderAll() {
    renderMode();
    renderPicker();
    renderRows();
    renderQuota();
  }

  function startPoll() {
    if (state.poll) return;
    state.poll = setInterval(function () {
      loadStatus();
      loadBusy();
      var any = Object.keys(state.inFlight).some(function (k) { return state.inFlight[k]; });
      if (!any) stopPoll();
    }, POLL_MS);
  }

  function stopPoll() {
    if (state.poll) { clearInterval(state.poll); state.poll = null; }
  }

  function doUpload(platform) {
    if (PLATFORMS.indexOf(platform) === -1) { setBanner(GLYPH.fail + ' blocked: ' + platform + ' social platform nahi hai', 'no'); return; }
    if (!state.selected) { setBanner(GLYPH.warn + ' pehle dua chunein', 'no'); return; }
    if (state.liveMode) {
      var ok = window.confirm('LIVE upload: ' + PLATFORM_LABEL[platform] + '\n\nDua: ' + state.selected
        + '\n\nAsli platform pe upload hoga. Confirm karein?');
      if (!ok) return;
    }
    state.inFlight[platform] = true;
    setBanner(GLYPH.wait + ' ' + PLATFORM_LABEL[platform] + ' upload chal raha hai...', '');
    renderRows();
    startPoll();

    request('POST', '/upload/' + platform + '/' + encodeURIComponent(state.selected) + '?dry_run=' + dryFlag())
      .then(function (r) { handleUploadResult(r, platform); })
      .catch(function (e) {
        state.inFlight[platform] = false;
        setBanner(GLYPH.fail + ' network error: ' + e.message, 'no');
        renderRows();
        stopPoll();
      });
  }

  function handleUploadResult(r, platform) {
    state.inFlight[platform] = false;
    if (r.status === 200) {
      var url = r.body && (r.body.url || r.body.video_url);
      if (r.body && r.body.dry_run === true) {
        setBanner(GLYPH.done + ' ' + PLATFORM_LABEL[platform] + ' dry-run OK - kuch upload nahi hua.', 'ok');
      } else {
        setBanner(GLYPH.done + ' ' + PLATFORM_LABEL[platform] + ' upload complete' + (url ? ': ' + url : ''), 'ok');
      }
    } else if (r.status === 409) {
      setBanner(GLYPH.busy + ' ' + PLATFORM_LABEL[platform] + ' already chal raha hai, wait karein', 'no');
    } else if (r.status === 429) {
      setBanner(GLYPH.warn + ' quota exceed ho gaya (YouTube). Kal try karein.', 'no');
    } else {
      setBanner(GLYPH.fail + ' ' + PLATFORM_LABEL[platform] + ': ' + errorText(r), 'no');
    }
    loadStatus();
    loadBusy();
    loadQuota();
    renderRows();
    if (!Object.keys(state.inFlight).some(function (k) { return state.inFlight[k]; })) stopPoll();
  }

  function doUploadAll() {
    if (!state.selected) { setBanner(GLYPH.warn + ' pehle dua chunein', 'no'); return; }
    if (state.liveMode) {
      var ok = window.confirm('LIVE upload: TikTok + Instagram + Facebook\n\nDua: ' + state.selected
        + '\n\nAsli platform pe teeno upload honge. YouTube bilkul touch nahi hoga. Confirm karein?');
      if (!ok) return;
    }
    var dua = state.selected;
    PLATFORMS.forEach(function (p) { state.inFlight[p] = true; });
    setBanner(GLYPH.wait + ' teeno platforms par upload chal raha hai...', '');
    renderRows();
    startPoll();

    var results = {};
    var pending = PLATFORMS.length;

    function settle(platform, r) {
      var one = (r && r.body) || {};
      if (r && (r.status === 200 || r.status === 207)) {
        one.ok = true;
      } else {
        one.ok = false;
        one.message = r ? errorText(r) : 'network error';
      }
      results[platform] = one;
      pending -= 1;
      if (pending > 0) return;
      handleAllResult({ status: 207, body: { results: results } });
    }

    PLATFORMS.forEach(function (p) {
      request('POST', '/upload/' + p + '/' + encodeURIComponent(dua) + '?dry_run=' + dryFlag())
        .then(function (r) { settle(p, r); })
        .catch(function () { settle(p, null); });
    });
  }

  function handleAllResult(r) {
    PLATFORMS.forEach(function (p) { state.inFlight[p] = false; });
    var b = r.body || {};
    if (r.status === 200) {
      var allDry = PLATFORMS.every(function (p) { var o = (b.results || {})[p] || {}; return o.dry_run === true; });
      setBanner(GLYPH.done + (allDry ? ' teeno platforms dry-run OK - kuch upload nahi hua.' : ' teeno platforms complete.'), 'ok');
    } else if (r.status === 207) {
      var results = b.results || {};
      var parts = PLATFORMS.map(function (p) {
        var one = results[p] || {};
        var good = one.ok === true || one.status === GLYPH.done || !!one.url;
        var glyph = typeof one.status === 'string' && one.status ? one.status : (good ? GLYPH.done : GLYPH.fail);
        return glyph + ' ' + PLATFORM_LABEL[p]
          + (good ? ' ' + dryLabel(one, true) : ': ' + (one.message || one.error || one.failure || 'failed'));
      });
      var allGood = PLATFORMS.every(function (p) { var o = results[p] || {}; return o.ok === true || !!o.url; });
      var everyDry = allGood && PLATFORMS.every(function (p) { return (results[p] || {}).dry_run === true; });
      if (everyDry) {
        setBanner(GLYPH.done + ' teeno platforms dry-run OK - kuch upload nahi hua.', 'ok');
      } else {
        setBanner(GLYPH.warn + ' partial result - ' + parts.join(' | '), 'no');
      }
      renderPartial(results);
    } else if (r.status === 429) {
      setBanner(GLYPH.warn + ' quota exceed ho gaya (YouTube). Kal try karein.', 'no');
    } else {
      setBanner(GLYPH.fail + ' ' + errorText(r), 'no');
    }
    loadStatus();
    loadBusy();
    loadQuota();
    renderRows();
    stopPoll();
  }

  function doRetry(platform) {
    if (PLATFORMS.indexOf(platform) === -1) { setBanner(GLYPH.fail + ' blocked: ' + platform + ' social platform nahi hai', 'no'); return; }
    if (!state.selected) { setBanner(GLYPH.warn + ' pehle dua chunein', 'no'); return; }
    if (state.liveMode) {
      var ok = window.confirm('LIVE retry: ' + PLATFORM_LABEL[platform] + '\n\nDua: ' + state.selected
        + '\n\nConfirm karein?');
      if (!ok) return;
    }
    state.inFlight[platform] = true;
    setBanner(GLYPH.wait + ' ' + PLATFORM_LABEL[platform] + ' retry chal raha hai...', '');
    renderRows();
    startPoll();
    request('POST', '/upload/retry/' + encodeURIComponent(state.selected) + '/' + platform + '?dry_run=' + dryFlag())
      .then(function (r) { handleUploadResult(r, platform); })
      .catch(function (e) {
        state.inFlight[platform] = false;
        setBanner(GLYPH.fail + ' network error: ' + e.message, 'no');
        renderRows();
        stopPoll();
      });
  }

  function toggleMode() {
    if (state.liveMode) {
      state.liveMode = false;
      setBanner(GLYPH.info + ' DRY RUN mode on. Koi asli upload nahi hoga.', 'ok');
    } else {
      var ok = window.confirm('LIVE mode enable karein?\n\nIske baad Upload button asli platform pe upload karega.\n\nRecommended: pehle dry run karein.');
      if (!ok) return;
      state.liveMode = true;
      setBanner(GLYPH.warn + ' LIVE mode on. Ab asli upload hoga.', 'no');
    }
    renderMode();
    renderRows();
  }

  function onClick(e) {
    var t = e.target;
    if (!t || !t.getAttribute) return;
    var act = t.getAttribute('data-act');
    if (!act) return;
    if (act === 'upload') {
      var p = t.getAttribute('data-platform');
      var rec = state.selected ? platformRecord(state.selected, p) : null;
      if (rec && rec.phase === 'completed') doRetry(p); else doUpload(p);
    } else if (act === 'all') {
      doUploadAll();
    }
  }

  function mount() {
    var host = el('socialContainer');
    if (!host || host.getAttribute('data-mounted') === '1') return;
    host.setAttribute('data-mounted', '1');
    host.innerHTML = ''
      + '<div class="panel-body" id="social_body">'
      + '  <div id="social_banner" class="aihint">Social upload manager. Default DRY RUN hai.</div>'
      + '  <div class="panel-section">'
      + '    <div class="panel-section-title">Mode</div>'
      + '    <div class="yt-form-row">'
      + '      <div id="social_mode" class="aihint ok" style="flex:1">DRY RUN mode</div>'
      + '      <button class="btn-sm" id="social_modebtn" onclick="socialToggleMode()">Enable live upload</button>'
      + '    </div>'
      + '  </div>'
      + '  <div class="panel-section">'
      + '    <div class="panel-section-title">Dua</div>'
      + '    <div class="yt-form-row">'
      + '      <input id="social_search" placeholder="dua dhundo..." oninput="socialFilter(this.value)" style="flex:1">'
      + '      <select id="social_picker" onchange="socialSelect(this.value)" style="min-width:260px"></select>'
      + '    </div>'
      + '  </div>'
      + '  <div class="panel-section">'
      + '    <div class="panel-section-title">Quota</div>'
      + '    <div id="social_quota"></div>'
      + '  </div>'
      + '  <div id="social_partial"></div>'
      + '  <div id="social_rows"></div>'
      + '</div>';
    host.addEventListener('click', onClick);
  }

  function init() {
    mount();
    renderAll();
    loadDuas().then(function () { return loadStatus(); }).then(function () {
      return loadBusy();
    }).then(function () { return loadQuota(); });
  }

  window.socialOpen = function () {
    var hub = el('socialHub');
    if (!hub) return;
    hub.style.display = 'block';
    state.open = true;
    init();
  };

  window.socialClose = function () {
    var hub = el('socialHub');
    if (hub) hub.style.display = 'none';
    state.open = false;
    state.liveMode = false;
    renderMode();
    stopPoll();
  };

  window.socialToggleMode = toggleMode;
  window.socialFilter = function (v) { state.filter = v || ''; renderPicker(); };
  window.socialSelect = function (v) {
    state.selected = v || null;
    setBanner(state.selected ? (GLYPH.info + ' chuna hua: ' + state.selected) : '', '');
    renderRows();
  };
})();
