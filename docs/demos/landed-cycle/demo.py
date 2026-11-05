"""Synthetic Git/forge fixture: no live lifecycle calls or forge requests.

Run against a chosen source directory, or this checkout by default. The merged-PR
metadata seam is an explicit fixture; real Git creates the squash and SHAs.
"""
import pathlib,tempfile,subprocess,sys,json
sys.path.insert(0,sys.argv[1] if len(sys.argv)>1 else str(pathlib.Path(__file__).resolve().parents[3]))
from shantytown.workspace import tree_staleness
from shantytown.cycle import assess

def git(p,*a):
    return subprocess.check_output(['git','-C',str(p),*a],stderr=subprocess.DEVNULL,text=True).strip()
with tempfile.TemporaryDirectory() as t:
    p=pathlib.Path(t); origin=p/'origin.git'; seed=p/'seed'; agent=p/'agent'
    subprocess.run(['git','init','--bare','-b','main',str(origin)],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['git','clone',str(origin),str(seed)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for r in [seed]:
        git(r,'config','user.name','Fixture'); git(r,'config','user.email','fixture@example.org')
    (seed/'base').write_text('base');git(seed,'add','.');git(seed,'commit','-m','base');git(seed,'push','origin','main')
    subprocess.run(['git','clone',str(origin),str(agent)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    git(agent,'config','user.name','Fixture');git(agent,'config','user.email','fixture@example.org');git(agent,'checkout','-b','feature')
    for n in range(2):
        (agent/f'file{n}').write_text(str(n));git(agent,'add','.');git(agent,'commit','-m',f'feature {n}')
    git(agent,'push','-u','origin','feature');git(seed,'fetch','origin');git(seed,'merge','--squash','origin/feature');git(seed,'commit','-m','squash feature');git(seed,'push','origin','main');git(seed,'push','origin','--delete','feature')
    try:
        from shantytown import landed
    except ImportError:
        pass  # Baseline source has no landing-proof path.
    else:
        original = landed.forge_identity
        landed.forge_identity = lambda url: ('https://forge.example','forge.example','fixture/repo') if url == str(origin) else original(url)
        row = {'number':7,'state':'closed','merged_at':'2026-01-01T00:00:00Z', 'base':{'repo':{'full_name':'fixture/repo'}}, 'head':{'sha':git(agent,'rev-parse','HEAD')}, 'merge_commit_sha':git(seed,'rev-parse','HEAD')}
        landed.read_merged_prs = lambda url: [row]
    s=tree_staleness(agent,fetch=True,tracked_only=True)
    v=assess('fixture',[str(agent)],'fixture checkpoint',lambda _:s,reachable=lambda _:True)
    print(json.dumps({'scenario':'two squash-landed commits, deleted remote head','unpushed':s.unpushed,'cycle_allowed':v.ok,'render':s.render()}))
    (agent/'new').write_text('unpublished');git(agent,'add','.');git(agent,'commit','-m','unpublished')
    s=tree_staleness(agent,fetch=True,tracked_only=True)
    v=assess('fixture',[str(agent)],'fixture checkpoint',lambda _:s,reachable=lambda _:True)
    print(json.dumps({'scenario':'same plus genuinely unpublished commit','unpushed':s.unpushed,'cycle_allowed':v.ok,'render':s.render()}))
