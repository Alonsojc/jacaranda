(function () {
  'use strict';
  var state = {page:1, view:'diario', seq:0, connectionSeq:0, busy:false, total:0, ready:false, rows:[], filters:null, link:null};
  var dias = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo'];
  var plan = {seq:0, editorSeq:0, people:[], mode:'', week:'', saving:false};
  var planTypes = {semanal:'Semanal', apoyo:'Apoyo', cobertura:'Cobertura', ajuste:'Cambio de horario', descanso:'Descanso', sin_turno:'Sin turno programado'};
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
  function durationLabel(seconds) {
    if (!Number.isInteger(seconds) || seconds < 0) return '\u2014';
    var hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60), remainder = seconds % 60;
    var parts = [];
    if (hours) parts.push(hours + ' h');
    if (minutes) parts.push(minutes + ' min');
    if (remainder || !parts.length) parts.push(remainder + ' s');
    return parts.join(' ');
  }
  function calculationStatus(row) {
    if (row.estado_calculo === 'sin_incidencias') return '<span class="att-linked">Pares registrados</span>';
    if (row.estado_calculo !== 'revisar') return '<span class="att-unlinked">No disponible</span>';
    var labels = {
      entrada_sin_salida:'Falta salida', salida_sin_entrada:'Falta entrada',
      entrada_repetida:'Entradas repetidas', codigo_desconocido:'C\u00f3digo sin clasificar',
      marcas_simultaneas:'Marcas simult\u00e1neas', secuencia_incierta:'Secuencia incierta'
    };
    var details = Array.isArray(row.motivos_calculo) ? row.motivos_calculo.map(function(code) {
      return labels[code] || 'Requiere revisi\u00f3n';
    }) : [];
    return '<span class="att-unlinked">Revisar</span>' + (details.length ? '<small>' + esc(details.join(' \u00b7 ')) + '</small>' : '');
  }
  function hoursCell(row) {
    var label = durationLabel(row.segundos_completos);
    return '<span class="att-time att-duration">' + esc(label) + '</span>' +
      (row.estado_calculo === 'revisar' && label !== '\u2014' ? '<small>Parcial</small>' : '');
  }
  function markType(row) {
    return row.tipo === 'entrada' ? 'Entrada' : row.tipo === 'salida' ? 'Salida' : 'Sin clasificar';
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
    var syncingWeek = state.busy && state.view === 'horarios';
    el('plan').querySelectorAll('button,input').forEach(function(control) { control.disabled = syncingWeek; });
  }
  function clearRows() {
    state.rows = []; state.total = 0;
    el('body').innerHTML = '<tr><td class="att-empty" colspan="' + (state.view === 'diario' ? 8 : 7) + '">Sin datos cargados</td></tr>';
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
      ? '<tr><th>Persona</th><th>D\u00eda</th><th>Primera marca</th><th>\u00daltima marca</th><th>Horas registradas</th><th>Marcas</th><th>Estado</th><th>Vinculaci\u00f3n</th></tr>'
      : '<tr><th>Persona</th><th>Fecha</th><th>Hora</th><th>Tipo</th><th>C\u00f3digo original</th><th>Equipo</th><th>Vinculaci\u00f3n</th></tr>';
    el('body').innerHTML = data.items.length ? data.items.map(function(row, index) {
      var person = '<strong>' + esc(row.empleado_nombre || row.nombre_reloj || 'Sin nombre') + '</strong><small>Reloj ' + esc(row.numero_reloj) + '</small>';
      var link = row.empleado_id ? '<span class="att-linked">Vinculada</span>' : (canEdit() ? '<button type="button" class="att-link" data-link="' + index + '">Vincular</button>' : '<span class="att-unlinked">Pendiente</span>');
      var cells = daily
        ? [['D\u00eda',esc(dateLabel(row.dia))],['Primera marca','<span class="att-time">'+esc(timeLabel(row.primera))+'</span>'],['\u00daltima marca','<span class="att-time">'+esc(timeLabel(row.ultima))+'</span>'],['Horas registradas',hoursCell(row)],['Marcas',esc(row.marcas)],['Estado',calculationStatus(row)]]
        : [['Fecha',esc(dateLabel(row.fecha))],['Hora','<span class="att-time">'+esc(timeLabel(row.fecha))+'</span>'],['Tipo',esc(markType(row))],['C\u00f3digo original',esc(row.tipo_original)],['Equipo',esc(row.dispositivo_nombre || 'Sin nombre')+'<small>'+esc(row.dispositivo)+'</small>']];
      return '<tr><td>' + person + '</td>' + cells.map(function(cell) { return '<td data-label="' + esc(cell[0]) + '">' + cell[1] + '</td>'; }).join('') + '<td data-label="Vinculaci\u00f3n">' + link + '</td></tr>';
    }).join('') : '<tr><td class="att-empty" colspan="' + (daily ? 8 : 7) + '">Sin checadas en este periodo</td></tr>';
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
    var planning = state.view === 'horarios';
    var feedback = planning ? function(text,error) { planMessage('plan-feedback',text,error); } : message;
    var filters;
    try {
      if (planning) {
        var today = fechaHoyISO(), week = plan.week, end = plusDays(week,6);
        if (week > today) throw new Error('La semana seleccionada todavía no empieza.');
        filters = {desde:week,hasta:end > today ? today : end};
      } else {
        filters = readFilters();
        if (filters.days >= 7) throw new Error('Sincroniza hasta 7 d\u00edas por consulta.');
      }
    } catch(error) { feedback(error.message,true); return; }
    var seq = ++state.seq, session = _versionSesion;
    state.busy = true; controls(); feedback('Consultando CrossChex…');
    try {
      var result = await request('POST','/sincronizar',{desde:filters.desde,hasta:filters.hasta});
      if (!current(seq,session)) return;
      if (planning) await loadPlan();
      else { state.busy = false; await load(true); }
      if (session !== _versionSesion) return;
      state.busy = false;
      await connection();
      if (session === _versionSesion) feedback(result.nuevas + ' nuevas, ' + result.repetidas + ' repetidas y ' + result.omitidas_otro_equipo + ' de otros equipos omitidas.');
    } catch (error) {
      if (current(seq,session)) feedback(error.message || 'No se pudo sincronizar. Puedes reintentar sin duplicar checadas.',true);
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

  function weekDay(isoDate) { return (new Date(isoDate + 'T00:00:00Z').getUTCDay() + 6) % 7; }
  function plusDays(isoDate, days) {
    var date = new Date(isoDate + 'T00:00:00Z');
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0,10);
  }
  function planMessage(id, text, error) {
    el(id).textContent = text || '';
    el(id).classList.toggle('error', !!error);
  }
  function renderPlan(data) {
    plan.people = data.personas;
    el('plan-actions').hidden = !canEdit();
    el('plan-link-clock').hidden = !data.personas.some(function(person) { return !person.numero_reloj; });
    el('plan-totals').innerHTML = data.resumen.length ? data.resumen.map(function(row) {
      var note = '';
      if (!row.numero_reloj) note = '<small>Pendiente de vincular al checador</small>';
      else if (row.dias_por_revisar) note = '<small>Días por revisar: ' + esc(row.dias_por_revisar) + '</small>';
      return '<tr><td><strong>' + esc(row.nombre) + '</strong></td><td data-label="Programadas"><span class="att-time">' +
        esc(row.minutos_programados ? durationLabel(row.minutos_programados * 60) : '0 h') + '</span></td>' +
        '<td data-label="Registradas en el reloj"><span class="att-time">' + esc(durationLabel(row.segundos_registrados)) +
        '</span>' + note + '</td></tr>';
    }).join('') : '<tr><td colspan="3" class="att-empty">Agrega al equipo para ver los totales.</td></tr>';
    el('plan-body').innerHTML = data.items.length ? data.items.map(function(row) {
      var hours = row.horas ? esc(row.horas.entrada + '–' + row.horas.salida) : '—';
      var note = row.nota ? '<small>' + esc(row.nota) + '</small>' : '';
      var outside = row.horas && row.modalidad === 'compras' ? '<small>Incluye compras fuera del local</small>' : '';
      var worked = '<span class="att-time att-duration">' + esc(durationLabel(row.segundos_registrados)) + '</span>' +
        (row.revisar_marcas ? '<small>Revisar marcas</small>' : '');
      var day = dias[weekDay(row.fecha)] + ', ' + dateLabel(row.fecha);
      return '<tr><td><strong>' + esc(row.nombre) + '</strong></td><td data-label="Día" class="att-plan-day">' + esc(day) +
        '</td><td data-label="Horario programado"><span class="att-time">' + hours + '</span>' + outside +
        '</td><td data-label="Horas registradas">' + worked + '</td><td data-label="Tipo de turno">' +
        esc(planTypes[row.tipo] || '') + note + '</td></tr>';
    }).join('') : '<tr><td colspan="5" class="att-empty">Sin turnos ni checadas en esta semana.</td></tr>';
  }
  async function loadPlan() {
    var selected = el('plan-week').value || fechaHoyISO();
    el('plan-week').value = selected;
    var seq = ++plan.seq, session = _versionSesion;
    el('plan-actions').hidden = true;
    el('plan-body').innerHTML = ''; el('plan-totals').innerHTML = '';
    planMessage('plan-feedback','Cargando horarios…');
    try {
      var from = plusDays(selected, -weekDay(selected)), to = plusDays(from, 6);
      plan.week = from;
      el('plan-range').textContent = dateLabel(from) + ' – ' + dateLabel(to);
      var data = await request('GET','/horarios?desde=' + encodeURIComponent(from) + '&hasta=' + encodeURIComponent(to));
      if (seq !== plan.seq || session !== _versionSesion) return;
      if (!Array.isArray(data.items) || !Array.isArray(data.personas) || !Array.isArray(data.resumen)) throw new Error('Respuesta de horarios no válida.');
      renderPlan(data);
      planMessage('plan-feedback','');
      return true;
    } catch (error) {
      if (seq === plan.seq && session === _versionSesion) planMessage('plan-feedback',error.message || 'No se pudieron consultar los horarios.',true);
    }
  }
  function shiftWeek(days) {
    if (!plan.week) return;
    el('plan-week').value = plusDays(plan.week, days);
    loadPlan();
  }
  function showPlanField(id, show) {
    el(id).hidden = !show;
    el(id).disabled = !show;
  }
  function planSettings(data) {
    var weekday = weekDay(el('plan-date').value);
    var weekly = data.semanal || {};
    var byDate = data.fecha;
    var settings = (plan.mode === 'fecha' && byDate) || weekly;
    dias.forEach(function(_, index) {
      var hours = (weekly.dias || {})[index] || {};
      el('plan-day-start-' + index).value = hours.entrada || '';
      el('plan-day-end-' + index).value = hours.salida || '';
    });
    var hours = (byDate ? byDate.horas : (weekly.dias || {})[weekday]) || {};
    el('plan-kind').value = byDate ? byDate.tipo : 'apoyo';
    el('plan-start').value = hours.entrada || '';
    el('plan-end').value = hours.salida || '';
    el('plan-mode').value = settings.modalidad || 'sucursal';
    el('plan-note').value = settings.nota || '';
    el('plan-restore').hidden = plan.mode !== 'fecha' || !byDate;
    planTimeFields();
  }
  function planTimeFields() {
    var working = plan.mode !== 'fecha' || el('plan-kind').value !== 'descanso';
    el('plan-hours').hidden = !working;
    el('plan-start').disabled = !working;
    el('plan-end').disabled = !working;
    el('plan-mode-field').hidden = !working;
  }
  async function loadPlanSettings() {
    var person = el('plan-person').value, date = el('plan-date').value;
    var seq = ++plan.editorSeq, session = _versionSesion;
    el('plan-save').disabled = true;
    planMessage('plan-error','');
    planSettings({});
    if (!person || !date) return;
    try {
      var data = await request('GET','/horarios/personas/' + encodeURIComponent(person) + '?fecha=' + encodeURIComponent(date));
      if (seq !== plan.editorSeq || session !== _versionSesion || !el('plan-dialog').open) return;
      planSettings(data);
      el('plan-save').disabled = false;
    } catch (error) {
      if (seq === plan.editorSeq && session === _versionSesion) planMessage('plan-error',error.message || 'No se pudo consultar el horario.',true);
    }
  }
  function openPlan(mode) {
    if (!canEdit() || state.busy) return;
    if (mode !== 'persona' && !plan.people.length) {
      planMessage('plan-feedback','Agrega una persona antes de programar su horario.',true);
      return;
    }
    plan.mode = mode;
    el('plan-title').textContent = {persona:'Agregar persona', reloj:'Vincular checador', semanal:'Horario semanal', fecha:'Turno por fecha'}[mode];
    el('plan-date-label').textContent = mode === 'semanal' ? 'Vigente desde' : 'Fecha';
    showPlanField('plan-new',mode === 'persona');
    showPlanField('plan-clock',mode === 'persona' || mode === 'reloj');
    el('plan-clock-select').hidden = mode !== 'reloj';
    el('plan-clock-person').required = mode === 'reloj';
    el('plan-clock-number').required = mode === 'reloj';
    showPlanField('plan-editor',mode === 'semanal' || mode === 'fecha');
    showPlanField('plan-days',mode === 'semanal');
    showPlanField('plan-specific',mode === 'fecha');
    el('plan-name').value = ''; el('plan-clock-number').value = '';
    el('plan-date').value = el('plan-week').value || fechaHoyISO();
    el('plan-person').innerHTML = '<option value="">Selecciona una persona</option>' + plan.people.map(function(person) {
      return '<option value="' + esc(person.id) + '">' + esc(person.nombre) + '</option>';
    }).join('');
    el('plan-clock-person').innerHTML = '<option value="">Selecciona una persona</option>' + plan.people.filter(function(person) {
      return !person.numero_reloj;
    }).map(function(person) { return '<option value="' + esc(person.id) + '">' + esc(person.nombre) + '</option>'; }).join('');
    el('plan-save').disabled = mode === 'semanal' || mode === 'fecha';
    planMessage('plan-error','');
    planSettings({});
    el('plan-dialog').showModal();
  }
  function planHours(entrada, salida, day) {
    if (!entrada || !salida || salida <= entrada) {
      throw new Error('Indica una entrada y una salida posterior' + (day ? ' para el ' + day : '') + '.');
    }
    return {entrada:entrada,salida:salida};
  }
  async function savePlan(restore) {
    if (!canEdit() || plan.saving || el('plan-save').disabled) return;
    var session = _versionSesion;
    var person = el('plan-person').value, date = el('plan-date').value;
    var path = '/horarios/personas', method = 'PUT', body;
    planMessage('plan-error','');
    plan.saving = true; el('plan-save').disabled = true; el('plan-restore').disabled = true;
    el('plan-editor').disabled = true;
    el('plan-new').disabled = true; el('plan-clock').disabled = true;
    try {
      if (plan.mode === 'persona') {
        method = 'POST'; body = {nombre:el('plan-name').value.trim(),numero_reloj:el('plan-clock-number').value.trim() || null};
      } else if (plan.mode === 'reloj') {
        path += '/' + encodeURIComponent(el('plan-clock-person').value) + '/reloj';
        body = {numero_reloj:el('plan-clock-number').value.trim()};
      } else {
        path += '/' + encodeURIComponent(person);
        body = {modalidad:el('plan-mode').value, nota:el('plan-note').value.trim()};
        if (plan.mode === 'semanal') {
          path += '/semanal'; body.vigente_desde = date; body.dias = {};
          dias.forEach(function(dia, index) {
            var entrada = el('plan-day-start-' + index).value, salida = el('plan-day-end-' + index).value;
            if (entrada || salida) body.dias[index] = planHours(entrada, salida, dia);
          });
        } else {
          path += '/fechas/' + encodeURIComponent(date);
          if (restore) { method = 'DELETE'; body = undefined; }
          else {
            body.tipo = el('plan-kind').value;
            body.horas = body.tipo === 'descanso' ? null : planHours(el('plan-start').value,el('plan-end').value);
          }
        }
      }
      await request(method,path,body);
      if (session !== _versionSesion) return;
      el('plan-dialog').close();
      if (plan.mode === 'semanal' || plan.mode === 'fecha') el('plan-week').value = date;
      if (await loadPlan()) planMessage('plan-feedback',{
        persona:'Persona agregada.',reloj:'Checador vinculado.',semanal:'Horario guardado.',fecha:'Horario guardado.'
      }[plan.mode]);
    } catch (error) {
      if (session === _versionSesion) planMessage('plan-error',error.message || 'No se pudo guardar.',true);
    } finally {
      if (session === _versionSesion) {
        plan.saving = false; el('plan-save').disabled = false; el('plan-restore').disabled = false;
        el('plan-new').disabled = plan.mode !== 'persona';
        el('plan-clock').disabled = plan.mode !== 'persona' && plan.mode !== 'reloj';
        el('plan-editor').disabled = plan.mode !== 'semanal' && plan.mode !== 'fecha';
      }
    }
  }
  function showAttendanceView(view) {
    var scheduling = view === 'horarios';
    el('records').hidden = scheduling;
    el('export').hidden = scheduling;
    el('plan').hidden = !scheduling;
    el('tabs').querySelectorAll('button').forEach(function(tab) { tab.setAttribute('aria-selected',String(tab.dataset.view === view)); });
  }
  window.initAsistencia = async function() {
    if (state.view === 'horarios') return loadPlan();
    var session = _versionSesion;
    if (!el('from').value) { el('from').value = fechaHoyISO(); el('to').value = fechaHoyISO(); }
    await load(false);
    if (session === _versionSesion) await connection();
  };
  window.resetAsistencia = function() {
    state.seq++; state.connectionSeq++; state.busy = false; state.ready = false; state.filters = null; state.link = null; state.page = 1; state.view = 'diario';
    if (!el('body')) return;
    plan.seq++; plan.editorSeq++; plan.people = []; plan.saving = false; plan.week = ''; plan.mode = '';
    el('plan-dialog').close(); el('plan-person').innerHTML = ''; el('plan-clock-person').innerHTML = '';
    el('plan-clock-number').value = ''; el('plan-body').innerHTML = ''; el('plan-totals').innerHTML = '';
    el('plan-week').value = ''; el('plan-date').value = ''; el('plan-range').textContent = ''; el('plan-name').value = '';
    planSettings({}); planMessage('plan-feedback',''); planMessage('plan-error',''); showAttendanceView('diario');
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
      showAttendanceView(state.view);
      if (state.view === 'horarios') loadPlan();
      else load(true);
    });
    el('plan-days').innerHTML = '<div class="att-plan-day-row att-plan-day-heading"><span>Día</span><span>Entrada</span><span>Salida</span></div>' + dias.map(function(day, index) {
      return '<div class="att-plan-day-row"><strong class="att-plan-day">' + day + '</strong>' +
        '<input type="time" id="att-plan-day-start-' + index + '" aria-label="Entrada ' + day + '">' +
        '<input type="time" id="att-plan-day-end-' + index + '" aria-label="Salida ' + day + '"></div>';
    }).join('');
    el('plan-filter').addEventListener('submit',function(event) { event.preventDefault(); loadPlan(); });
    el('plan-prev').addEventListener('click',function() { shiftWeek(-7); });
    el('plan-next').addEventListener('click',function() { shiftWeek(7); });
    el('plan-actions').addEventListener('click',function(event) {
      var button = event.target.closest('[data-plan]');
      if (button) openPlan(button.dataset.plan);
    });
    ['plan-person','plan-date'].forEach(function(id) { el(id).addEventListener('change',loadPlanSettings); });
    el('plan-kind').addEventListener('change',planTimeFields);
    el('plan-close').addEventListener('click',function() { if (!plan.saving) el('plan-dialog').close(); });
    el('plan-dialog').addEventListener('cancel',function(event) { if (plan.saving) event.preventDefault(); });
    el('plan-form').addEventListener('submit',function(event) { event.preventDefault(); savePlan(false); });
    el('plan-restore').addEventListener('click',function() { savePlan(true); });
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
