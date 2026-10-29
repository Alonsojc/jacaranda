(function () {
  'use strict';
  var state = {page:1, view:'diario', seq:0, connectionSeq:0, busy:false, total:0, ready:false, rows:[], filters:null, link:null};
  function el(id) { return document.getElementById('att-' + id); }
  function esc(value) { return escHtml(String(value == null ? '' : value)); }
  function canEdit() { return (window._permisos || {}).asistencia === 'editar'; }
  function request(method, path, body) {
    return api(method, '/asistencia' + path, body, false, null, null, {silenciosa:true, timeoutMs:60000});
  }
  function message(text, error) { el('feedback').textContent = text || ''; el('feedback').classList.toggle('error', !!error); }
  function current(seq, session) { return seq === state.seq && session === _versionSesion; }
  function timeLabel(value) {
    if (!value) return '\u2014';
    return new Intl.DateTimeFormat('es-MX', {timeZone:APP_TIMEZONE, hour:'2-digit', minute:'2-digit', hour12:false}).format(new Date(value));
  }
  function dateLabel(value) {
    return new Intl.DateTimeFormat('es-MX', {timeZone:APP_TIMEZONE, day:'numeric', month:'short', year:'numeric'}).format(new Date(value.length === 10 ? value + 'T12:00:00-06:00' : value));
  }
  function readFilters() {
    var from = el('from').value, to = el('to').value;
    var days = (Date.parse(to + 'T00:00:00Z') - Date.parse(from + 'T00:00:00Z')) / 86400000;
    if (!from || !to || !Number.isFinite(days) || days < 0 || days >= 31) throw new Error('Selecciona un periodo de 1 a 31 d\u00edas.');
    return {desde:from, hasta:to, buscar:el('search').value.trim(), days:days};
  }
  function query(filters) {
    return '?desde=' + encodeURIComponent(filters.desde) + '&hasta=' + encodeURIComponent(filters.hasta) + '&buscar=' + encodeURIComponent(filters.buscar);
  }
  function controls() {
    el('sync').hidden = !canEdit();
    el('sync').disabled = state.busy || !state.ready;
    el('export').disabled = state.busy || !state.rows.length;
    el('previous').disabled = state.busy || state.page <= 1;
    el('next').disabled = state.busy || state.page * 25 >= state.total;
    el('save-link').disabled = state.busy || !canEdit();
    document.querySelectorAll('#att-body [data-link]').forEach(function(button) { button.disabled = state.busy; });
  }
  function clearRows() {
    state.rows = []; state.total = 0;
    el('body').innerHTML = '<tr><td class="att-empty" colspan="6">Sin datos cargados</td></tr>';
    ['marks','people','pending'].forEach(function(id) { el(id).textContent = '\u2014'; });
    el('range').textContent = ''; el('page').textContent = '';
  }
  function render(data) {
    state.rows = data.items; state.total = data.total;
    el('marks').textContent = data.resumen.marcas;
    el('people').textContent = data.resumen.personas;
    el('pending').textContent = data.resumen.sin_vincular;
    var daily = state.view === 'diario';
    el('head').innerHTML = daily
      ? '<tr><th>Persona</th><th>D\u00eda</th><th>Primera marca</th><th>\u00daltima marca</th><th>Marcas</th><th>Vinculaci\u00f3n</th></tr>'
      : '<tr><th>Persona</th><th>Fecha</th><th>Hora</th><th>C\u00f3digo original</th><th>Equipo</th><th>Vinculaci\u00f3n</th></tr>';
    el('body').innerHTML = data.items.length ? data.items.map(function(row, index) {
      var person = '<strong>' + esc(row.empleado_nombre || row.nombre_reloj || 'Sin nombre') + '</strong><small>Reloj ' + esc(row.numero_reloj) + '</small>';
      var link = row.empleado_id ? '<span class="att-linked">Vinculada</span>' : (canEdit() ? '<button type="button" class="att-link" data-link="' + index + '">Vincular</button>' : '<span class="att-unlinked">Pendiente</span>');
      var cells = daily
        ? [['D\u00eda',esc(dateLabel(row.dia))],['Primera marca','<span class="att-time">'+esc(timeLabel(row.primera))+'</span>'],['\u00daltima marca','<span class="att-time">'+esc(timeLabel(row.ultima))+'</span>'],['Marcas',esc(row.marcas)]]
        : [['Fecha',esc(dateLabel(row.fecha))],['Hora','<span class="att-time">'+esc(timeLabel(row.fecha))+'</span>'],['C\u00f3digo original',esc(row.tipo_original)],['Equipo',esc(row.dispositivo_nombre || 'Sin nombre')+'<small>'+esc(row.dispositivo)+'</small>']];
      return '<tr><td>' + person + '</td>' + cells.map(function(cell) { return '<td data-label="' + esc(cell[0]) + '">' + cell[1] + '</td>'; }).join('') + '<td data-label="Vinculaci\u00f3n">' + link + '</td></tr>';
    }).join('') : '<tr><td class="att-empty" colspan="6">Sin checadas en este periodo</td></tr>';
    el('range').textContent = data.total ? ((state.page-1)*25+1) + '\u2013' + Math.min(state.page*25,data.total) + ' de ' + data.total : '0 registros';
    el('page').textContent = state.page + ' / ' + Math.max(1,Math.ceil(data.total/25));
  }
  async function load(reset) {
    if (state.busy) return;
    if (reset) state.page = 1;
    var seq = ++state.seq, session = _versionSesion;
    state.busy = true; clearRows(); controls(); message('Cargando checadas...');
    try {
      if (reset || !state.filters) state.filters = readFilters();
      var data = await request('GET','/checadas' + query(state.filters) + '&vista=' + state.view + '&pagina=' + state.page);
      if (!current(seq,session)) return;
      if (!Array.isArray(data.items) || !data.resumen) throw new Error('Respuesta no v\u00e1lida. Vuelve a consultar.');
      render(data); message('');
    } catch (error) {
      if (current(seq,session)) { clearRows(); message(error.message || 'No se pudieron cargar las checadas.',true); }
    } finally { if (current(seq,session)) { state.busy = false; controls(); } }
  }
  async function connection() {
    var seq = ++state.connectionSeq, session = _versionSesion;
    try {
      var data = await request('GET','/estado');
      if (seq !== state.connectionSeq || session !== _versionSesion) return;
      state.ready = !!data.lista;
      el('status').textContent = data.lista ? 'Conexi\u00f3n configurada' : 'Conexi\u00f3n pendiente';
      el('status').classList.toggle('ready',!!data.lista);
      el('last-sync').textContent = data.ultima_sincronizacion ? '\u00daltima sincronizaci\u00f3n: ' + dateLabel(data.ultima_sincronizacion) + ', ' + timeLabel(data.ultima_sincronizacion) : 'Sin sincronizaciones';
      el('timezone').textContent = data.zona_horaria || APP_TIMEZONE;
      controls();
    } catch (error) {
      if (seq === state.connectionSeq && session === _versionSesion) { state.ready = false; el('status').textContent = 'Conexi\u00f3n no verificada'; controls(); }
    }
  }
  async function sync() {
    if (state.busy || !canEdit() || !state.ready) return;
    var filters;
    try { filters = readFilters(); if(filters.days >= 7) throw new Error('Sincroniza hasta 7 d\u00edas por consulta.'); }
    catch(error) { message(error.message,true); return; }
    var seq = ++state.seq, session = _versionSesion;
    state.busy = true; controls(); message('Consultando CrossChex...');
    try {
      var result = await request('POST','/sincronizar',{desde:filters.desde,hasta:filters.hasta});
      if (!current(seq,session)) return;
      state.busy = false;
      await load(true); await connection();
      if (session === _versionSesion) message(result.nuevas + ' nuevas, ' + result.repetidas + ' repetidas y ' + result.omitidas_otro_equipo + ' de otros equipos omitidas.');
    } catch (error) {
      if (current(seq,session)) message(error.message || 'No se pudo sincronizar. Puedes reintentar sin duplicar checadas.',true);
    } finally { if (session === _versionSesion) { state.busy = false; controls(); } }
  }
  async function openLink(index) {
    if (state.busy || !canEdit()) return;
    var row = state.rows[index];
    if (!row || row.empleado_id) return;
    state.link = row.numero_reloj;
    el('link-name').textContent = (row.nombre_reloj || 'Sin nombre') + ' \u00b7 Reloj ' + row.numero_reloj;
    el('employee').innerHTML = '<option value="">Cargando empleados...</option>';
    el('reason').value = ''; el('link-error').textContent = '';
    el('dialog').showModal(); state.busy = true; controls();
    var seq = state.seq, session = _versionSesion;
    try {
      var people = await request('GET','/empleados');
      if (!current(seq,session) || !el('dialog').open) return;
      el('employee').innerHTML = '<option value="">' + (people.length ? 'Seleccionar empleado' : 'Sin empleados activos') + '</option>' + people.map(function(p) {
        return '<option value="' + esc(p.id) + '">' + esc(p.nombre + ' (' + p.numero_empleado + ')') + '</option>';
      }).join('');
    } catch (error) { if (current(seq,session)) el('link-error').textContent = 'No se pudieron consultar los empleados.'; }
    finally { if (current(seq,session)) { state.busy = false; controls(); } }
  }
  async function saveLink(event) {
    event.preventDefault();
    if (state.busy || !canEdit() || !state.link) return;
    var seq = ++state.seq, session = _versionSesion;
    state.busy = true; controls();
    try {
      await request('POST','/vinculos',{numero_reloj:state.link,empleado_id:Number(el('employee').value),motivo:el('reason').value.trim()});
      if (!current(seq,session)) return;
      el('dialog').close(); state.link = null; state.busy = false;
      await load(false);
    } catch(error) { if(current(seq,session)) el('link-error').textContent = error.message || 'No se pudo vincular.'; }
    finally { if(session === _versionSesion) { state.busy = false; controls(); } }
  }
  window.initAsistencia = async function() {
    var session = _versionSesion;
    if (!el('from').value) { el('from').value = fechaHoyISO(); el('to').value = fechaHoyISO(); }
    await load(false);
    if (session === _versionSesion) await connection();
  };
  window.resetAsistencia = function() {
    state.seq++; state.connectionSeq++; state.busy = false; state.ready = false; state.filters = null; state.link = null; state.page = 1;
    if (!el('body')) return;
    clearRows(); el('dialog').close(); el('employee').innerHTML = ''; el('link-name').textContent = '';
    el('reason').value = ''; el('search').value = ''; el('from').value = ''; el('to').value = '';
    el('link-error').textContent = ''; el('last-sync').textContent = '';
    el('status').textContent = 'Conexi\u00f3n pendiente'; el('status').classList.remove('ready'); message(''); controls();
  };
  document.addEventListener('DOMContentLoaded',function() {
    el('filters').addEventListener('submit',function(event) { event.preventDefault(); load(true); });
    el('sync').addEventListener('click',sync);
    el('previous').addEventListener('click',function() { if(!state.busy && state.page>1) { state.page--; load(false); } });
    el('next').addEventListener('click',function() { if(!state.busy && state.page*25<state.total) { state.page++; load(false); } });
    el('tabs').addEventListener('click',function(event) {
      var button = event.target.closest('[data-view]');
      if (!button || state.busy) return;
      state.view = button.dataset.view;
      el('tabs').querySelectorAll('button').forEach(function(tab) { tab.setAttribute('aria-selected',String(tab===button)); });
      load(true);
    });
    el('body').addEventListener('click',function(event) { var b=event.target.closest('[data-link]'); if(b) openLink(Number(b.dataset.link)); });
    el('link-form').addEventListener('submit',saveLink);
    el('close-link').addEventListener('click',function() { el('dialog').close(); });
    el('cancel-link').addEventListener('click',function() { el('dialog').close(); });
    el('export').addEventListener('click',function() {
      if (state.busy || !state.filters || !state.rows.length) return;
      descargarArchivoAutenticado('/api/v1/asistencia/exportar' + query(state.filters),'asistencia-' + state.filters.desde + '-' + state.filters.hasta + '.csv','Checadas descargadas','No se pudo exportar');
    });
  });
}());
