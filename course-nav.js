'use strict';
// One route registry. Resolve against this script, never the domain root.
(() => {
  const base=new URL('./',document.currentScript.src);
  const nav=document.querySelector('[data-course-nav]')||document.querySelector('nav[aria-label="Course navigation"]');
  if(!nav)return;
  const routes=[['','Option Surface Lab'],['covered-call/','Covered call'],['covered-call/data.html','Data & method'],['pmcc/','PMCC']];
  nav.setAttribute('aria-label','Course navigation');nav.classList.add('course-navigation');
  nav.replaceChildren(...routes.map(([path,label])=>{
    const a=document.createElement('a');a.href=new URL(path,base).href;a.textContent=label;
    const here=location.pathname.replace(/index\.html$/,'').replace(/options_surface_preview\.html$/,'');
    if(here===new URL(a.href).pathname)a.setAttribute('aria-current','page');
    return a;
  }));
  const css=document.createElement('link');css.rel='stylesheet';css.href=new URL('course-nav.css',base).href;document.head.append(css);
})();
