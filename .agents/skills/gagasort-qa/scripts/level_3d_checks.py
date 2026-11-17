"""三维高度三角形相交；以XY裁剪定位共同内部，再比较两平面的真实Z。"""
import math
EPS=1e-5; AREA=1e-5
def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def clip(a,b):
 p=[list(v[:2]) for v in a];sgn=1 if cross(*b)>0 else -1
 for k in range(3):
  q=[];u=b[k];v=b[(k+1)%3]
  for i,x in enumerate(p):
   y=p[(i+1)%len(p)];dx=cross(u,v,x)*sgn;dy=cross(u,v,y)*sgn
   if dx>=0:q.append(x)
   if (dx>=0)!=(dy>=0):
    t=dx/(dx-dy);q.append([x[j]+(y[j]-x[j])*t for j in range(2)])
  p=q
  if not p:break
 return p
def area(p):return abs(sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p))))*.5 if len(p)>2 else 0
def height(t,p):
 a,b,c=t;den=cross(a,b,c);u=cross(a,p,c)/den;v=cross(a,b,p)/den
 return a[2]+u*(b[2]-a[2])+v*(c[2]-a[2])
def relation(a,b):
 p=clip(a,b);ar=area(p)
 if ar<=AREA:return {'kind':'disjoint_or_boundary','projected_area':ar}
 ds=[height(a,x)-height(b,x) for x in p];lo=min(ds);hi=max(ds)
 kind='coplanar_overlap' if max(abs(lo),abs(hi))<=EPS else 'transverse_intersection' if lo<-EPS and hi>EPS else 'height_separated' if lo>EPS or hi<-EPS else 'boundary_or_tolerance_contact'
 return {'kind':kind,'projected_area':ar,'min_height_delta':lo,'max_height_delta':hi,'xy_polygon':p,'xyz_on_a':[[x[0],x[1],height(a,x)] for x in p]}
def smoke():
 a=[[0,0,0],[4,0,0],[0,4,0]];b=[[.5,.5,0],[2,.5,0],[.5,2,0]]
 assert relation(a,b)['kind']=='coplanar_overlap'
 assert relation(a,[[x,y,3] for x,y,z in b])['kind']=='height_separated'
 assert relation(a,[[.5,.5,-1],[2,.5,1],[.5,2,1]])['kind']=='transverse_intersection'
 assert relation(a,[[4,0,0],[5,0,0],[4,1,0]])['kind']=='disjoint_or_boundary'
 assert relation(a,[[10,10,0],[12,10,0],[10,12,0]])['kind']=='disjoint_or_boundary'
 assert relation(a,list(reversed(b)))['kind']=='coplanar_overlap'
 return 'passed: coplanar overlap, height-separated bridge, transverse slope, edge-only contact, disjoint, reversed winding'
def triangles(mesh,kind):
 vs=mesh['vertices'];ts=mesh['triangles'];out=[]
 for k in range(0,len(ts),3):
  ids=ts[k:k+3]
  if kind=='wall':
   side=1 if all(x%8 in [1,2] for x in ids) else -1 if all(x%8 in [5,6] for x in ids) else 0
   if not side:continue
   row=min(ids)//8
  else:
   if any(x%4 in [0,3] for x in ids):continue
   row=min(ids)//4;side=0
  t=[vs[i] for i in ids]
  if abs(cross(*t))<=AREA:continue
  out.append({'id':k//3,'row':row,'side':side,'vertices':t,'min':list(map(min,zip(*t))),'max':list(map(max,zip(*t)))})
 return out
def analyze(mesh,kind,rows,arc,threshold):
 ts=triangles(mesh,kind);ordered=sorted(ts,key=lambda x:x['min'][0]);counts={k:0 for k in ['coplanar_overlap','transverse_intersection','height_separated','boundary_or_tolerance_contact']};evidence=[];local=0;remote=0;candidate=0;separated_examples=[]
 for i,a in enumerate(ordered):
  for b in ordered[i+1:]:
   if b['min'][0]>=a['max'][0]:break
   dist=abs(a['row']-b['row'])
   if a['side']==b['side'] and (dist<=1 or dist>=rows-2):continue
   if a['max'][1]<=b['min'][1] or b['max'][1]<=a['min'][1]:continue
   r=relation(a['vertices'],b['vertices'])
   if r['kind']=='disjoint_or_boundary':continue
   candidate+=1;counts[r['kind']]+=1
   if r['kind'] in ['coplanar_overlap','transverse_intersection','boundary_or_tolerance_contact']:
    sep=abs(arc[a['row']]-arc[b['row']]);sep=min(sep,arc[-1]-sep);nonlocal_=sep>threshold
    if r['kind']!='boundary_or_tolerance_contact':
     remote+=int(nonlocal_);local+=int(not nonlocal_)
    if len(evidence)<30:evidence.append({'triangles':[a['id'],b['id']],'rows':[a['row'],b['row']],'sides':[a['side'],b['side']],'path_separation':sep,'nonlocal':nonlocal_,'vertices':[a['vertices'],b['vertices']],**r})
   elif len(separated_examples)<5:separated_examples.append({'triangles':[a['id'],b['id']],'rows':[a['row'],b['row']],**r})
 # Water is emitted as a height surface over the board XY; cross.Z determines upward winding even on slopes.
 folds=sum(cross(*t['vertices']) < -AREA for t in ts) if kind=='water' else None
 return {'tested_triangles':len(ts),'positive_area_xy_candidates':candidate,'counts':counts,'nonlocal_intersections':remote,'local_intersections':local,'winding_negative_z':folds,'intersection_evidence':evidence,'height_separated_examples':separated_examples}
