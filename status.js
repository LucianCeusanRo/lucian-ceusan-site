/* Shared status loader for the portfolio. Reads the live monitor output from the
   status-data branch; falls back to the snapshot shipped with the site. A fetch
   error never turns anything red: unknown is not the same as down. */
(function(){
  var LIVE='https://raw.githubusercontent.com/LucianCeusanRo/lucian-ceusan-site/status-data/status.json';
  function get(u){return fetch(u+(u.indexOf('?')<0?'?':'&')+'t='+Math.floor(Date.now()/120000),{cache:'no-store'}).then(function(r){if(!r.ok)throw 0;return r.json()})}
  window.loadStatus=function(cb){
    get(LIVE).catch(function(){return get('/status.json')}).then(function(s){
      if(!s||!s.demos)throw 0;
      s.stale=(Date.now()-Date.parse(s.updated))>6*3600*1000;
      cb(s);
    }).catch(function(){cb(null)});
  };
})();
