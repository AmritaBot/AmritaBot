/**
 * Amrita WebUI - 共享权限编辑工具 v2
 *
 * 左右分栏设计：左侧标签面板 + 右侧表格编辑器。
 * 所有权限页面共享此模块。
 *
 * 全局: window.PermEditor
 *   PermEditor.init({ containerId, tagsContainerId, dataStr, saveUrl, onSaved })
 *   PermEditor.addEntry(key, value)
 *   PermEditor.save()
 */

(function () {
  "use strict";

  var _uid = 0;
  function uid() { return "pe-" + (++_uid) + "-" + Date.now().toString(36); }

  /**
   * 权限标签定义：左侧快速面板的预设权限前缀
   */
  var DEFAULT_TAGS = [
    { label: "admin.*", prefix: "admin.*", value: "true", color: "purple" },
    { label: "command.*", prefix: "command.*", value: "true", color: "blue" },
    { label: "chat.*", prefix: "chat.*", value: "true", color: "green" },
    { label: "chat.send", prefix: "chat.send", value: "true", color: "emerald" },
    { label: "chat.reply", prefix: "chat.reply", value: "true", color: "teal" },
    { label: "perm.*", prefix: "perm.*", value: "true", color: "orange" },
    { label: "menu.*", prefix: "menu.*", value: "true", color: "pink" },
  ];

  var TAG_COLORS = {
    purple: "bg-purple-100 text-purple-700 border-purple-300 dark:bg-purple-900/30 dark:text-purple-300 dark:border-purple-700",
    blue:   "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-700",
    green:  "bg-green-100 text-green-700 border-green-300 dark:bg-green-900/30 dark:text-green-300 dark:border-green-700",
    emerald:"bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700",
    teal:   "bg-teal-100 text-teal-700 border-teal-300 dark:bg-teal-900/30 dark:text-teal-300 dark:border-teal-700",
    orange: "bg-orange-100 text-orange-700 border-orange-300 dark:bg-orange-900/30 dark:text-orange-300 dark:border-orange-700",
    pink:   "bg-pink-100 text-pink-700 border-pink-300 dark:bg-pink-900/30 dark:text-pink-300 dark:border-pink-700",
  };

  var _data = {};
  var _containerId, _tagsContainerId, _saveUrl, _onSaved, _tagElems;

  function init(opts) {
    _containerId = opts.containerId;
    _tagsContainerId = opts.tagsContainerId || "";
    _saveUrl = opts.saveUrl;
    _onSaved = opts.onSaved || null;
    var tags = opts.tags || DEFAULT_TAGS;

    _data = {};
    if (opts.dataStr) {
      opts.dataStr.split("\n").forEach(function (line) {
        var t = line.trim();
        if (!t) return;
        var idx = t.lastIndexOf(" ");
        if (idx > 0) _data[t.slice(0, idx)] = t.slice(idx + 1).trim();
      });
    }

    if (_tagsContainerId) renderTags(tags);
    renderTable();
  }

  function renderTags(tags) {
    var tc = document.getElementById(_tagsContainerId);
    if (!tc) return;
    tc.innerHTML = "";
    _tagElems = {};

    tags.forEach(function (tag) {
      var state = getTagState(tag.prefix);
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "perm-tag px-3 py-1.5 rounded-full text-xs font-medium border transition-all cursor-pointer " +
        getTagStyle(tag.color, state);
      chip.textContent = tag.label + (state === "true" ? " 持有" : state === "false" ? " 禁止" : "");
      chip.title = "点击切换: 未设置 → 持有 → 禁止 → 移除";

      chip.addEventListener("click", function () { toggleTag(tag, chip); });
      tc.appendChild(chip);
      _tagElems[tag.prefix] = { el: chip, tag: tag, state: state };
    });
  }

  function getTagState(prefix) {
    return _data.hasOwnProperty(prefix) ? _data[prefix] : "none";
  }

  function getTagStyle(color, state) {
    var base = TAG_COLORS[color] || TAG_COLORS.blue;
    if (state === "true")  return base + " ring-2 ring-green-400/60";
    if (state === "false") return base + " opacity-50 line-through ring-1 ring-red-400/40";
    return base + " opacity-60 hover:opacity-90";
  }

  function toggleTag(tag, chip) {
    var cur = getTagState(tag.prefix);
    if (cur === "none") _data[tag.prefix] = "true";
    else if (cur === "true") _data[tag.prefix] = "false";
    else delete _data[tag.prefix];
    renderTable();
    var ns = getTagState(tag.prefix);
    chip.className = "perm-tag px-3 py-1.5 rounded-full text-xs font-medium border transition-all cursor-pointer " + getTagStyle(tag.color, ns);
    chip.textContent = tag.label + (ns === "true" ? " 持有" : ns === "false" ? " 禁止" : "");
  }

  function renderTable() {
    var container = document.getElementById(_containerId);
    if (!container) return;
    var keys = Object.keys(_data).sort();
    if (keys.length === 0) {
      container.innerHTML = '<div class="text-center py-16 text-gray-400 dark:text-gray-500">' +
        '<i class="fas fa-shield-alt text-4xl mb-3 block opacity-30"></i>' +
        '<p class="text-sm">暂无权限条目</p><p class="text-xs mt-1 opacity-60">点击左侧标签快速添加，或手动输入</p></div>';
      return;
    }

    var html = '<div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="border-b border-gray-200 dark:border-gray-700 text-left text-gray-500 dark:text-gray-400 text-xs uppercase tracking-wider">' +
      '<th class="py-2 pl-3">权限节点</th><th class="py-2 w-20">状态</th><th class="py-2 pr-3 w-12"></th></tr></thead><tbody>';

    keys.forEach(function (key) {
      var val = _data[key], isTrue = val === "true";
      var bc = isTrue ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                      : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
      html += '<tr class="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer perm-row" data-key="' + _escAttr(key) + '">' +
        '<td class="py-2 pl-3"><code class="text-xs font-mono text-gray-700 dark:text-gray-300">' + _esc(key) + '</code></td>' +
        '<td class="py-2"><span class="inline-block px-2 py-0.5 rounded-full text-xs font-medium ' + bc + '">' + (isTrue ? "持有" : "禁止") + '</span></td>' +
        '<td class="py-2 pr-3"><button class="text-gray-400 hover:text-red-500 transition-colors perm-del-btn" data-key="' + _escAttr(key) + '" title="删除"><i class="fas fa-times"></i></button></td></tr>';
    });
    html += '</tbody></table></div>';
    container.innerHTML = html;

    container.querySelectorAll(".perm-row").forEach(function (row) {
      row.addEventListener("click", function (e) {
        if (e.target.closest(".perm-del-btn")) return;
        var key = row.dataset.key;
        _data[key] = _data[key] === "true" ? "false" : "true";
        renderTable();
        updateTagIf(key);
      });
    });
    container.querySelectorAll(".perm-del-btn").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        delete _data[btn.dataset.key];
        renderTable();
        updateTagIf(btn.dataset.key);
      });
    });
  }

  function updateTagIf(key) {
    if (!_tagElems || !_tagElems[key]) return;
    var t = _tagElems[key];
    t.state = getTagState(key);
    t.el.className = "perm-tag px-3 py-1.5 rounded-full text-xs font-medium border transition-all cursor-pointer " + getTagStyle(t.tag.color, t.state);
    t.el.textContent = t.tag.label + (t.state === "true" ? " 持有" : t.state === "false" ? " 禁止" : "");
  }

  function addEntry(key, value) {
    if (!key) return;
    _data[key] = value || "true";
    renderTable();
  }

  function showAddDialog() {
    Swal.fire({
      title: "添加权限",
      html: '<input id="swal-perm-key" class="swal2-input" placeholder="权限节点（如 my.custom）">' +
            '<select id="swal-perm-val" class="swal2-input"><option value="true">持有</option><option value="false">禁止</option></select>',
      showCancelButton: true,
      confirmButtonText: "添加",
      preConfirm: function () {
        var key = document.getElementById("swal-perm-key").value.trim();
        if (!key) { Swal.showValidationMessage("请输入权限节点"); return false; }
        return { key: key, value: document.getElementById("swal-perm-val").value };
      }
    }).then(function (r) {
      if (r.isConfirmed) addEntry(r.value.key, r.value.value);
    });
  }

  function save() {
    var lines = [];
    Object.keys(_data).sort().forEach(function (k) { lines.push(k + " " + _data[k]); });
    var permStr = lines.join("\n");
    var fd = new FormData();
    fd.append("permissions", permStr);
    fetch(_saveUrl, { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.success || j.code === 200) {
          Swal.fire({ icon: "success", title: "保存成功", text: j.message, timer: 1500, showConfirmButton: false });
          if (_onSaved) _onSaved();
        } else Swal.fire({ icon: "error", title: "保存失败", text: j.message });
      })
      .catch(function (e) { Swal.fire({ icon: "error", title: "网络错误", text: String(e) }); });
  }

  function _esc(s)  { return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
  function _escAttr(s) { return String(s).replace(/&/g,"&amp;").replace(/"/g,"&quot;"); }

  window.PermEditor = { init: init, addEntry: addEntry, showAddDialog: showAddDialog, save: save, DEFAULT_TAGS: DEFAULT_TAGS };
})();
