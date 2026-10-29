// Local-only preview: shipped view/module, fictional data, no external requests.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'docs/index.html'), 'utf8');
const start = html.indexOf('<div class="page" id="asistencia">');
const section = html.slice(start, html.indexOf('<div class="page" id="listas">', start)).replace('class="page"', 'class="page on"');
const css = html.slice(html.indexOf('<style>') + 7, html.indexOf('</style>'));
const port = Number(process.env.PREVIEW_PORT || 8784);

if (process.argv.includes('--detach')) {
  const child = require('node:child_process').spawn(process.execPath, [__filename], {
    detached:true, stdio:'ignore', env:process.env,
  });
  child.unref();
  console.log(`Preview PID ${child.pid}: http://127.0.0.1:${port}`);
} else {
  http.createServer((request, response) => {
    const url = new URL(request.url, `http://127.0.0.1:${port}`);
    if (url.pathname === '/favicon.ico') { response.writeHead(204); response.end(); return; }
    const assets = ['/js/asistencia.js', '/css/asistencia.css', '/icons/lucide/download.svg',
      '/icons/lucide/refresh-cw.svg', '/icons/lucide/chevron-left.svg', '/icons/lucide/chevron-right.svg', '/icons/lucide/x.svg'];
    if (assets.includes(url.pathname)) {
      const type = url.pathname.endsWith('.js') ? 'text/javascript' : url.pathname.endsWith('.css') ? 'text/css' : 'image/svg+xml';
      response.writeHead(200, {'Content-Type':type});
      response.end(fs.readFileSync(path.join(root, 'docs', url.pathname))); return;
    }
    if (url.pathname !== '/') { response.writeHead(404); response.end(); return; }
    const flags = {empty:url.searchParams.has('empty'), ready:url.searchParams.has('ready'), readonly:url.searchParams.has('readonly')};
    const body = `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'none'; img-src 'self'; font-src 'none'">
      <title>Jacaranda - Asistencia ficticia</title><style>${css}
      .preview-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:20px 24px;border-bottom:1px solid #e2d8d2;background:white}
      .preview-header small{color:#6b716e;font-size:12px}.preview-shell{max-width:1240px;margin:0 auto;padding:28px 24px}
      @media(max-width:600px){.preview-shell{padding:24px 16px}.preview-header{padding:16px}}</style>
      <link rel="stylesheet" href="/css/asistencia.css"></head><body>
      <header class="preview-header"><div class="logo">Jacaranda<span>sharing flavors</span></div><small>Vista local &middot; Datos ficticios</small></header>
      <main class="preview-shell">${section}</main>
      <script>
      var _versionSesion=1,APP_TIMEZONE='America/Mexico_City',flags=${JSON.stringify(flags)};
      window._permisos={asistencia:flags.readonly?'ver':'editar'};
      function fechaHoyISO(){return '2026-10-28';}
      function escHtml(v){return String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');}
      var names=['Ana Demo','Mar Demo','Persona de prueba con un nombre muy largo','Lucia Demo','Pablo Demo'];
      var marks=flags.empty?[]:Array.from({length:56},function(_,i){return {id:i+1,numero_reloj:String(i%5+1).padStart(3,'0'),nombre_reloj:names[i%5],empleado_id:i%5===2?null:i%5+1,empleado_nombre:null,
      fecha:'2026-10-28T'+String(8+Math.floor(i/5)).padStart(2,'0')+':'+String(i%5*3).padStart(2,'0')+':00-06:00',tipo_original:i%2?129:128,dispositivo:'DEMO-EP30',dispositivo_nombre:'Mostrador de prueba'};});
      function api(method,path,body){return new Promise(function(resolve,reject){setTimeout(function(){
        var u=new URL(path,'http://local');
        if(path.includes('/estado'))return resolve({lista:flags.ready,ultima_sincronizacion:flags.empty?null:'2026-10-28T18:00:00-06:00',zona_horaria:APP_TIMEZONE});
        if(path.includes('/sincronizar'))return resolve({nuevas:0,repetidas:marks.length,omitidas_otro_equipo:0});
        if(path.includes('/empleados'))return resolve(names.map((n,i)=>({id:i+1,nombre:n,numero_empleado:'DEMO'+(i+1)})));
        if(path.includes('/vinculos')){marks.forEach(r=>{if(r.numero_reloj===body.numero_reloj){r.empleado_id=body.empleado_id;r.empleado_nombre=names[body.empleado_id-1];}});return resolve({vinculado:true});}
        if(path.includes('/checadas')){
          var search=(u.searchParams.get('buscar')||'').toLowerCase();
          var filtered=marks.filter(r=>r.fecha.slice(0,10)>=u.searchParams.get('desde')&&r.fecha.slice(0,10)<=u.searchParams.get('hasta')&&(!search||r.nombre_reloj.toLowerCase().includes(search)||r.numero_reloj.includes(search))).slice().reverse();
          var rows=filtered;
          if(u.searchParams.get('vista')==='diario'){
            var groups={}; filtered.forEach(r=>{var g=groups[r.numero_reloj];if(!g)groups[r.numero_reloj]={...r,dia:'2026-10-28',primera:r.fecha,ultima:r.fecha,marcas:1};else{g.marcas++;g.primera=r.fecha;}});rows=Object.values(groups);
          }
          var pg=Number(u.searchParams.get('pagina')||1);
          return resolve({items:rows.slice((pg-1)*25,pg*25),total:rows.length,resumen:{marcas:filtered.length,personas:new Set(filtered.map(r=>r.numero_reloj)).size,sin_vincular:new Set(filtered.filter(r=>!r.empleado_id).map(r=>r.numero_reloj)).size}});
        }
        reject(new Error('Ruta no disponible en la vista ficticia'));
      },180);});}
      function descargarArchivoAutenticado(){document.getElementById('att-feedback').textContent='Exportacion simulada; sin datos reales.';}
      </script><script src="/js/asistencia.js"></script><script>document.addEventListener('DOMContentLoaded',function(){initAsistencia();});</script></body></html>`;
    response.writeHead(200, {'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});
    response.end(body);
  }).listen(port, '127.0.0.1', () => console.log(`Fictional local preview: http://127.0.0.1:${port}`));
}
