// Official notice text stays inside the product; geometry links are explanatory.
export function renderRecallCards(container,cards,onComponent){
  container.replaceChildren();
  for(const card of cards){
    const detail=document.createElement('details');detail.open=container.childElementCount===0;const summary=document.createElement('summary');summary.textContent=card.campaign+' · '+card.title;detail.append(summary);
    const article=document.createElement('article');article.className='recall-card';article.dataset.campaign=card.campaign;
    const h=document.createElement('h3');h.textContent=card.campaign+' · '+card.title;article.append(h);
    for(const [label,text] of [['Vehicle scope',card.model_scope],['Issue',card.summary],['Safety consequence',card.consequence],['Manufacturer remedy',card.remedy],['Illustration scope',card.geometry_scope]]){if(!text)continue;const p=document.createElement('p'),strong=document.createElement('strong');strong.textContent=label+': ';p.append(strong,document.createTextNode(text));article.append(p);}
    for(const [flag,text] of [[card.do_not_drive,'DO NOT DRIVE — follow the manufacturer remedy for affected vehicles.'],[card.park_outside,'PARK OUTSIDE — follow the manufacturer instructions.']])if(flag){const p=document.createElement('p');p.className='recall-urgent';p.textContent=text;article.prepend(p);}
    if(onComponent && card.component_id){const b=document.createElement('button');b.textContent='Show '+card.component_id.replaceAll('-',' ')+' region in 3D';b.addEventListener('click',()=>onComponent(card));article.append(b);}
    const a=document.createElement('a');a.textContent='Official campaign and VIN check ↗';a.href=card.official_url;a.target='_blank';a.rel='noopener noreferrer';article.append(a);
    const stamp=document.createElement('small');stamp.textContent='Official response checked: '+card.checked_at;article.append(stamp);detail.append(article);container.append(detail);
  }
}
