#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <d3d11.h>

static FILE *g_log;
static CRITICAL_SECTION g_lock;
static int g_warp, g_fakeswap, g_texshrink, g_bufshrink, g_hidewin;
static int g_no_audio, g_no_input, g_sleep0_ms;
static int g_render_off, g_autodrive, g_autostart;
static float g_start_delay_ms = 3000.0f;
static int g_wait_s = 300;
static unsigned char *g_base;

static void hlog(const char *fmt, ...)
{
    if (!g_log)
        return;
    EnterCriticalSection(&g_lock);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
    LeaveCriticalSection(&g_lock);
}

static int env_int(const char *name, int dflt)
{
    char buf[32];
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
    if (!n || n >= sizeof(buf))
        return dflt;
    return atoi(buf);
}

static int env_on(const char *name)
{
    char buf[8];
    DWORD n = GetEnvironmentVariableA(name, buf, sizeof(buf));
    return n > 0 && n < sizeof(buf) && buf[0] == '1';
}

#define MAX_OFFSETS 64
static char g_off_name[MAX_OFFSETS][32];
static unsigned long long g_off_val[MAX_OFFSETS];
static int g_off_count;

static void load_offsets(void)
{
    static char buf[4096];
    DWORD n = GetEnvironmentVariableA("ACHL_OFFSETS", buf, sizeof(buf));
    if (!n || n >= sizeof(buf))
        return;
    char *ctx = NULL;
    for (char *tok = strtok_s(buf, ",", &ctx); tok && g_off_count < MAX_OFFSETS;
         tok = strtok_s(NULL, ",", &ctx)) {
        char *eq = strchr(tok, '=');
        if (!eq || eq - tok >= 31)
            continue;
        memcpy(g_off_name[g_off_count], tok, eq - tok);
        g_off_name[g_off_count][eq - tok] = 0;
        g_off_val[g_off_count] = _strtoui64(eq + 1, NULL, 16);
        g_off_count++;
    }
    hlog("offsets: %d loaded", g_off_count);
}

static int off(const char *name, unsigned long long *out)
{
    for (int i = 0; i < g_off_count; i++) {
        if (strcmp(g_off_name[i], name) == 0) {
            *out = g_off_val[i];
            return 1;
        }
    }
    hlog("offset missing: %s", name);
    return 0;
}

static void *iat_patch(const char *dll, const char *func, void *repl)
{
    unsigned char *b = g_base;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)b;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(b + dos->e_lfanew);
    DWORD rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva)
        return NULL;
    IMAGE_IMPORT_DESCRIPTOR *imp = (IMAGE_IMPORT_DESCRIPTOR *)(b + rva);
    for (; imp->Name; imp++) {
        if (_stricmp((const char *)(b + imp->Name), dll) != 0)
            continue;
        IMAGE_THUNK_DATA *orig = (IMAGE_THUNK_DATA *)(b + imp->OriginalFirstThunk);
        IMAGE_THUNK_DATA *iat = (IMAGE_THUNK_DATA *)(b + imp->FirstThunk);
        for (; orig->u1.AddressOfData; orig++, iat++) {
            if (IMAGE_SNAP_BY_ORDINAL(orig->u1.Ordinal))
                continue;
            IMAGE_IMPORT_BY_NAME *ibn = (IMAGE_IMPORT_BY_NAME *)(b + orig->u1.AddressOfData);
            if (strcmp((const char *)ibn->Name, func) != 0)
                continue;
            void *prev = (void *)iat->u1.Function;
            DWORD old;
            if (!VirtualProtect(&iat->u1.Function, sizeof(void *), PAGE_READWRITE, &old))
                return NULL;
            iat->u1.Function = (ULONGLONG)repl;
            VirtualProtect(&iat->u1.Function, sizeof(void *), old, &old);
            hlog("hooked %s!%s", dll, func);
            return prev;
        }
    }
    hlog("import not found: %s!%s", dll, func);
    return NULL;
}

static void patch_vtable(void **vtbl, int idx, void *repl, void **out_orig)
{
    DWORD old;
    if (!VirtualProtect(&vtbl[idx], sizeof(void *), PAGE_READWRITE, &old)) {
        hlog("VirtualProtect failed on vtable slot %d", idx);
        return;
    }
    *out_orig = vtbl[idx];
    vtbl[idx] = repl;
    VirtualProtect(&vtbl[idx], sizeof(void *), old, &old);
}

static int patch_bytes(unsigned long long rva, const unsigned char *bytes, int n, const char *what)
{
    unsigned char *p = g_base + rva;
    if (p[0] == 0xE9) {
        hlog("%s at +0x%llx is already detoured, not patching", what, rva);
        return 0;
    }
    DWORD old;
    if (!VirtualProtect(p, 16, PAGE_EXECUTE_READWRITE, &old)) {
        hlog("VirtualProtect failed for %s", what);
        return 0;
    }
    memcpy(p, bytes, n);
    VirtualProtect(p, 16, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 16);
    hlog("patched %s at +0x%llx", what, rva);
    return 1;
}

typedef HWND(WINAPI *pfn_cwex)(DWORD, LPCWSTR, LPCWSTR, DWORD, int, int, int, int,
                               HWND, HMENU, HINSTANCE, LPVOID);
static pfn_cwex g_real_cwex;

static HWND WINAPI hk_cwex(DWORD exstyle, LPCWSTR cls, LPCWSTR name, DWORD style,
                           int x, int y, int w, int h, HWND parent, HMENU menu,
                           HINSTANCE inst, LPVOID param)
{
    style &= ~WS_VISIBLE;
    exstyle |= WS_EX_TOOLWINDOW;
    exstyle &= ~WS_EX_APPWINDOW;
    return g_real_cwex(exstyle, cls, name, style, x, y, w, h, parent, menu, inst, param);
}

typedef HRESULT(WINAPI *pfn_di8create)(HINSTANCE, DWORD, REFIID, LPVOID *, LPVOID);
static pfn_di8create g_real_di8create;

static HRESULT WINAPI hk_enumdevices(void *self, DWORD type, void *cb, void *ref, DWORD flags)
{
    (void)self; (void)type; (void)cb; (void)ref; (void)flags;
    return S_OK;
}

static HRESULT WINAPI hk_di8create(HINSTANCE inst, DWORD ver, REFIID riid, LPVOID *out,
                                   LPVOID outer)
{
    HRESULT hr = g_real_di8create(inst, ver, riid, out, outer);
    if (SUCCEEDED(hr) && out && *out) {
        void **vt = *(void ***)*out;
        void *orig;
        if (vt[4] != (void *)hk_enumdevices) {
            patch_vtable(vt, 4, (void *)hk_enumdevices, &orig);
            hlog("input devices hidden");
        }
    }
    return hr;
}

typedef void(WINAPI *pfn_sleep)(DWORD);
static pfn_sleep g_real_sleep;

static void WINAPI hk_sleep(DWORD ms)
{
    if (ms == 0 && g_sleep0_ms > 0) {
        g_real_sleep((DWORD)g_sleep0_ms);
        return;
    }
    g_real_sleep(ms);
}

#define FMOD_ERR_FILE_NOTFOUND 20
static volatile LONG g_banks_skipped;

static int WINAPI hk_loadbank(void *self, const char *file, unsigned int flags, void **bank)
{
    (void)self; (void)flags;
    if (bank)
        *bank = NULL;
    if (InterlockedIncrement(&g_banks_skipped) == 1)
        hlog("audio banks skipped, first was %s", file ? file : "?");
    return FMOD_ERR_FILE_NOTFOUND;
}

typedef HRESULT(WINAPI *pfn_shgfp)(HWND, int, HANDLE, DWORD, LPWSTR);
static pfn_shgfp g_real_shgfp;
static wchar_t g_docs[MAX_PATH];

static HRESULT WINAPI hk_shgfp(HWND hwnd, int folder, HANDLE token, DWORD flags, LPWSTR path)
{
    if (g_docs[0] && (folder & 0xFF) == 0x05) {
        wcscpy_s(path, MAX_PATH, g_docs);
        return S_OK;
    }
    return g_real_shgfp(hwnd, folder, token, flags, path);
}

#define SHRUNK_SLOTS 16384
static void *g_shrunk[SHRUNK_SLOTS];

static void shrunk_add(void *p)
{
    size_t h = ((size_t)p >> 4) % SHRUNK_SLOTS;
    EnterCriticalSection(&g_lock);
    for (int i = 0; i < 64; i++) {
        size_t s = (h + i) % SHRUNK_SLOTS;
        if (!g_shrunk[s]) {
            g_shrunk[s] = p;
            break;
        }
    }
    LeaveCriticalSection(&g_lock);
}

static int shrunk_has(void *p)
{
    size_t h = ((size_t)p >> 4) % SHRUNK_SLOTS;
    int found = 0;
    EnterCriticalSection(&g_lock);
    for (int i = 0; i < 64; i++) {
        size_t s = (h + i) % SHRUNK_SLOTS;
        if (!g_shrunk[s])
            break;
        if (g_shrunk[s] == p) {
            found = 1;
            break;
        }
    }
    LeaveCriticalSection(&g_lock);
    return found;
}

typedef HRESULT(WINAPI *pfn_srv)(ID3D11Device *, ID3D11Resource *,
                                 const D3D11_SHADER_RESOURCE_VIEW_DESC *,
                                 ID3D11ShaderResourceView **);
typedef HRESULT(WINAPI *pfn_tex2d)(ID3D11Device *, const D3D11_TEXTURE2D_DESC *,
                                   const D3D11_SUBRESOURCE_DATA *, ID3D11Texture2D **);
typedef HRESULT(WINAPI *pfn_buffer)(ID3D11Device *, const D3D11_BUFFER_DESC *,
                                    const D3D11_SUBRESOURCE_DATA *, ID3D11Buffer **);
static pfn_srv g_real_srv;
static pfn_tex2d g_real_tex2d;
static pfn_buffer g_real_buffer;

static HRESULT WINAPI hk_srv(ID3D11Device *dev, ID3D11Resource *res,
                             const D3D11_SHADER_RESOURCE_VIEW_DESC *desc,
                             ID3D11ShaderResourceView **out)
{
    if (res && shrunk_has(res)) {
        HRESULT hr = g_real_srv(dev, res, NULL, out);
        if (SUCCEEDED(hr))
            return hr;
    }
    return g_real_srv(dev, res, desc, out);
}

static HRESULT WINAPI hk_tex2d(ID3D11Device *dev, const D3D11_TEXTURE2D_DESC *desc,
                               const D3D11_SUBRESOURCE_DATA *data, ID3D11Texture2D **out)
{
    if (g_texshrink && desc && data &&
        !(desc->BindFlags & (D3D11_BIND_RENDER_TARGET | D3D11_BIND_DEPTH_STENCIL)) &&
        (desc->BindFlags & D3D11_BIND_SHADER_RESOURCE) &&
        desc->Usage != D3D11_USAGE_STAGING && desc->Width > 4 && desc->Height > 4 &&
        !(desc->MiscFlags & D3D11_RESOURCE_MISC_TEXTURECUBE) && desc->ArraySize <= 1) {
        D3D11_TEXTURE2D_DESC d = *desc;
        d.Width = 4;
        d.Height = 4;
        d.MipLevels = 1;
        d.ArraySize = 1;
        d.SampleDesc.Count = 1;
        d.SampleDesc.Quality = 0;
        d.Usage = D3D11_USAGE_DEFAULT;
        d.CPUAccessFlags = 0;
        d.MiscFlags = 0;
        d.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        HRESULT hr = g_real_tex2d(dev, &d, NULL, out);
        if (SUCCEEDED(hr)) {
            if (out && *out)
                shrunk_add(*out);
            return hr;
        }
    }
    return g_real_tex2d(dev, desc, data, out);
}

static HRESULT WINAPI hk_buffer(ID3D11Device *dev, const D3D11_BUFFER_DESC *desc,
                                const D3D11_SUBRESOURCE_DATA *data, ID3D11Buffer **out)
{
    if (g_bufshrink && desc && data && desc->ByteWidth > 1024 &&
        desc->Usage == D3D11_USAGE_IMMUTABLE &&
        (desc->BindFlags & (D3D11_BIND_VERTEX_BUFFER | D3D11_BIND_INDEX_BUFFER)) &&
        !(desc->BindFlags & (D3D11_BIND_CONSTANT_BUFFER | D3D11_BIND_SHADER_RESOURCE |
                             D3D11_BIND_UNORDERED_ACCESS)) &&
        desc->CPUAccessFlags == 0 && desc->MiscFlags == 0) {
        D3D11_BUFFER_DESC d = *desc;
        d.ByteWidth = 1024;
        d.Usage = D3D11_USAGE_DEFAULT;
        HRESULT hr = g_real_buffer(dev, &d, NULL, out);
        if (SUCCEEDED(hr))
            return hr;
    }
    return g_real_buffer(dev, desc, data, out);
}

static void hook_device(ID3D11Device *dev)
{
    if (!dev || !(g_texshrink || g_bufshrink))
        return;
    void **vt = *(void ***)dev;
    if (vt[5] == (void *)hk_tex2d)
        return;
    patch_vtable(vt, 3, (void *)hk_buffer, (void **)&g_real_buffer);
    patch_vtable(vt, 5, (void *)hk_tex2d, (void **)&g_real_tex2d);
    patch_vtable(vt, 7, (void *)hk_srv, (void **)&g_real_srv);
    hlog("device hooked for texture and buffer shrinking");
}

typedef HRESULT(WINAPI *pfn_create)(IDXGIAdapter *, D3D_DRIVER_TYPE, HMODULE, UINT,
                                    const D3D_FEATURE_LEVEL *, UINT, UINT, ID3D11Device **,
                                    D3D_FEATURE_LEVEL *, ID3D11DeviceContext **);
typedef HRESULT(WINAPI *pfn_create_swap)(IDXGIAdapter *, D3D_DRIVER_TYPE, HMODULE, UINT,
                                         const D3D_FEATURE_LEVEL *, UINT, UINT,
                                         const DXGI_SWAP_CHAIN_DESC *, IDXGISwapChain **,
                                         ID3D11Device **, D3D_FEATURE_LEVEL *,
                                         ID3D11DeviceContext **);
static pfn_create g_real_create;
static pfn_create_swap g_real_create_swap;

static HRESULT WINAPI hk_create(IDXGIAdapter *ad, D3D_DRIVER_TYPE dt, HMODULE sw, UINT flags,
                                const D3D_FEATURE_LEVEL *fl, UINT nfl, UINT sdk,
                                ID3D11Device **ppDev, D3D_FEATURE_LEVEL *pfl,
                                ID3D11DeviceContext **ppCtx)
{
    HRESULT hr = E_FAIL;
    if (g_warp)
        hr = g_real_create(NULL, D3D_DRIVER_TYPE_WARP, sw, flags, fl, nfl, sdk, ppDev, pfl, ppCtx);
    if (!g_warp || FAILED(hr))
        hr = g_real_create(ad, dt, sw, flags, fl, nfl, sdk, ppDev, pfl, ppCtx);
    if (SUCCEEDED(hr) && ppDev && *ppDev)
        hook_device(*ppDev);
    return hr;
}

typedef ULONG(WINAPI *pfn_addref)(void *);
typedef ULONG(WINAPI *pfn_release)(void *);
typedef HRESULT(WINAPI *pfn_createtex2d)(void *, const D3D11_TEXTURE2D_DESC *, const void *,
                                         void **);

typedef struct {
    void **vtbl;
    LONG ref;
    void *backbuffer;
    void *device;
    DXGI_SWAP_CHAIN_DESC desc;
} FakeSwap;

static void *g_fake_vt[18];

static ULONG WINAPI fs_AddRef(void *t) { return InterlockedIncrement(&((FakeSwap *)t)->ref); }

static ULONG WINAPI fs_Release(void *t)
{
    FakeSwap *f = (FakeSwap *)t;
    LONG r = InterlockedDecrement(&f->ref);
    if (r == 0) {
        if (f->backbuffer)
            ((pfn_release)(*(void ***)f->backbuffer)[2])(f->backbuffer);
        free(f);
    }
    return r;
}

static HRESULT WINAPI fs_QueryInterface(void *t, REFIID riid, void **ppv)
{
    (void)riid;
    if (!ppv)
        return E_POINTER;
    *ppv = t;
    fs_AddRef(t);
    return S_OK;
}

static HRESULT WINAPI fs_SetPrivateData(void *t, REFGUID g, UINT n, const void *d)
{ (void)t; (void)g; (void)n; (void)d; return S_OK; }
static HRESULT WINAPI fs_SetPrivateDataInterface(void *t, REFGUID g, const void *u)
{ (void)t; (void)g; (void)u; return S_OK; }
static HRESULT WINAPI fs_GetPrivateData(void *t, REFGUID g, UINT *n, void *d)
{ (void)t; (void)g; (void)n; (void)d; return DXGI_ERROR_NOT_FOUND; }
static HRESULT WINAPI fs_GetParent(void *t, REFIID riid, void **ppv)
{ (void)t; (void)riid; if (ppv) *ppv = NULL; return E_NOINTERFACE; }

static HRESULT WINAPI fs_GetDevice(void *t, REFIID riid, void **ppv)
{
    (void)riid;
    FakeSwap *f = (FakeSwap *)t;
    if (!ppv || !f->device)
        return E_POINTER;
    ((pfn_addref)(*(void ***)f->device)[1])(f->device);
    *ppv = f->device;
    return S_OK;
}

static HRESULT WINAPI fs_Present(void *t, UINT s, UINT fl)
{ (void)t; (void)s; (void)fl; return S_OK; }

static HRESULT WINAPI fs_GetBuffer(void *t, UINT buf, REFIID riid, void **ppv)
{
    (void)buf; (void)riid;
    FakeSwap *f = (FakeSwap *)t;
    if (!ppv || !f->backbuffer)
        return E_FAIL;
    ((pfn_addref)(*(void ***)f->backbuffer)[1])(f->backbuffer);
    *ppv = f->backbuffer;
    return S_OK;
}

static HRESULT WINAPI fs_SetFullscreenState(void *t, BOOL fs, void *o)
{ (void)t; (void)fs; (void)o; return S_OK; }
static HRESULT WINAPI fs_GetFullscreenState(void *t, BOOL *fs, void **o)
{ (void)t; if (fs) *fs = FALSE; if (o) *o = NULL; return S_OK; }
static HRESULT WINAPI fs_GetDesc(void *t, DXGI_SWAP_CHAIN_DESC *d)
{ if (d) *d = ((FakeSwap *)t)->desc; return S_OK; }
static HRESULT WINAPI fs_ResizeBuffers(void *t, UINT c, UINT w, UINT h, DXGI_FORMAT f, UINT fl)
{ (void)t; (void)c; (void)w; (void)h; (void)f; (void)fl; return S_OK; }
static HRESULT WINAPI fs_ResizeTarget(void *t, const DXGI_MODE_DESC *m)
{ (void)t; (void)m; return S_OK; }
static HRESULT WINAPI fs_GetContainingOutput(void *t, void **o)
{ (void)t; if (o) *o = NULL; return DXGI_ERROR_UNSUPPORTED; }
static HRESULT WINAPI fs_GetFrameStatistics(void *t, void *s)
{ (void)t; (void)s; return S_OK; }
static HRESULT WINAPI fs_GetLastPresentCount(void *t, UINT *c)
{ (void)t; if (c) *c = 0; return S_OK; }

static void fakeswap_vtbl(void)
{
    void *fns[18] = {
        (void *)fs_QueryInterface, (void *)fs_AddRef, (void *)fs_Release,
        (void *)fs_SetPrivateData, (void *)fs_SetPrivateDataInterface,
        (void *)fs_GetPrivateData, (void *)fs_GetParent, (void *)fs_GetDevice,
        (void *)fs_Present, (void *)fs_GetBuffer, (void *)fs_SetFullscreenState,
        (void *)fs_GetFullscreenState, (void *)fs_GetDesc, (void *)fs_ResizeBuffers,
        (void *)fs_ResizeTarget, (void *)fs_GetContainingOutput,
        (void *)fs_GetFrameStatistics, (void *)fs_GetLastPresentCount};
    memcpy(g_fake_vt, fns, sizeof(fns));
}

static HRESULT make_fake_swapchain(HMODULE sw, UINT flags, const D3D_FEATURE_LEVEL *fl,
                                   UINT nfl, UINT sdk, const DXGI_SWAP_CHAIN_DESC *scd,
                                   IDXGISwapChain **ppSwap, ID3D11Device **ppDev,
                                   D3D_FEATURE_LEVEL *pfl, ID3D11DeviceContext **ppCtx)
{
    ID3D11Device *dev = NULL;
    ID3D11DeviceContext *ctx = NULL;
    HRESULT hr = g_real_create(NULL, D3D_DRIVER_TYPE_WARP, sw, flags, fl, nfl, sdk, &dev, pfl, &ctx);
    if (FAILED(hr) || !dev)
        return FAILED(hr) ? hr : E_FAIL;
    D3D11_TEXTURE2D_DESC td;
    ZeroMemory(&td, sizeof(td));
    td.Width = (scd && scd->BufferDesc.Width) ? scd->BufferDesc.Width : 320;
    td.Height = (scd && scd->BufferDesc.Height) ? scd->BufferDesc.Height : 240;
    td.Format = (scd && scd->BufferDesc.Format) ? scd->BufferDesc.Format : DXGI_FORMAT_R8G8B8A8_UNORM;
    td.MipLevels = 1;
    td.ArraySize = 1;
    td.SampleDesc.Count = 1;
    td.Usage = D3D11_USAGE_DEFAULT;
    td.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    void **dvt = *(void ***)dev;
    void *bb = NULL;
    hr = ((pfn_createtex2d)dvt[5])(dev, &td, NULL, &bb);
    if (FAILED(hr) || !bb) {
        ((pfn_release)dvt[2])(dev);
        if (ctx)
            ((pfn_release)(*(void ***)ctx)[2])(ctx);
        return FAILED(hr) ? hr : E_FAIL;
    }
    fakeswap_vtbl();
    FakeSwap *f = (FakeSwap *)calloc(1, sizeof(FakeSwap));
    if (!f)
        return E_OUTOFMEMORY;
    f->vtbl = g_fake_vt;
    f->ref = 1;
    f->backbuffer = bb;
    f->device = dev;
    if (scd)
        f->desc = *scd;
    if (ppSwap)
        *ppSwap = (IDXGISwapChain *)f;
    if (ppDev)
        *ppDev = dev;
    if (ppCtx)
        *ppCtx = ctx;
    hlog("offscreen swapchain %ux%u", td.Width, td.Height);
    return S_OK;
}

static HRESULT WINAPI hk_create_swap(IDXGIAdapter *ad, D3D_DRIVER_TYPE dt, HMODULE sw,
                                     UINT flags, const D3D_FEATURE_LEVEL *fl, UINT nfl,
                                     UINT sdk, const DXGI_SWAP_CHAIN_DESC *scd,
                                     IDXGISwapChain **ppSwap, ID3D11Device **ppDev,
                                     D3D_FEATURE_LEVEL *pfl, ID3D11DeviceContext **ppCtx)
{
    HRESULT hr = E_FAIL;
    if (g_warp) {
        hr = g_real_create_swap(NULL, D3D_DRIVER_TYPE_WARP, sw, flags, fl, nfl, sdk, scd,
                                ppSwap, ppDev, pfl, ppCtx);
        if (FAILED(hr) && g_fakeswap)
            hr = make_fake_swapchain(sw, flags, fl, nfl, sdk, scd, ppSwap, ppDev, pfl, ppCtx);
    }
    if (!g_warp || FAILED(hr))
        hr = g_real_create_swap(ad, dt, sw, flags, fl, nfl, sdk, scd, ppSwap, ppDev, pfl, ppCtx);
    hlog("d3d device ready hr=0x%08lx warp=%d", (unsigned long)hr, g_warp);
    if (SUCCEEDED(hr) && ppDev && *ppDev)
        hook_device(*ppDev);
    return hr;
}

static int rd64(unsigned long long addr, unsigned long long *out)
{
    if (addr < 0x10000)
        return 0;
    MEMORY_BASIC_INFORMATION mbi;
    if (!VirtualQuery((void *)addr, &mbi, sizeof(mbi)) || mbi.State != MEM_COMMIT ||
        (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    *out = *(volatile unsigned long long *)addr;
    return 1;
}

typedef struct {
    unsigned long long sim, avatar, car, rm;
} Chain;

static int read_chain(Chain *c)
{
    unsigned long long pyi, pyi_sim, sim_cars, av_car, av_rm, v, begin, end;
    if (!off("pyi", &pyi) || !off("pyi_sim", &pyi_sim) || !off("sim_cars", &sim_cars) ||
        !off("av_car", &av_car) || !off("av_race_manager", &av_rm))
        return 0;
    if (!rd64((unsigned long long)g_base + pyi, &v) || !v)
        return 0;
    if (!rd64(v + pyi_sim, &c->sim) || !c->sim)
        return 0;
    if (!rd64(c->sim + sim_cars, &begin) || !rd64(c->sim + sim_cars + 8, &end) || !begin ||
        end <= begin)
        return 0;
    if (!rd64(begin, &c->avatar) || !c->avatar)
        return 0;
    if (!rd64(c->avatar + av_car, &c->car) || !c->car)
        return 0;
    if (!rd64(c->avatar + av_rm, &c->rm))
        c->rm = 0;
    return 1;
}

static float player_rpm(const Chain *c)
{
    unsigned long long phys, rpm;
    if (!off("av_phys", &phys) || !off("phys_rpm", &rpm))
        return -1.0f;
    return *(volatile float *)(c->avatar + phys + rpm);
}

typedef void (*pfn_this)(void *);
typedef void *(*pfn_ctor)(void *, void *);
typedef void (*pfn_set_ctrl)(void *, void *);
typedef void (*pfn_start_race)(void *, float);

static int install_ai(Chain *c)
{
    unsigned long long start_game, ctor, init_tyres, set_ctrl, pref, tyres, cur_off, defs_off,
        def_size, laps_off;
    if (!off("start_game", &start_game) || !off("ai_ctor", &ctor) ||
        !off("ai_init_tyres", &init_tyres) || !off("set_controller", &set_ctrl) ||
        !off("ai_pref_compound", &pref) || !off("car_tyres", &tyres) ||
        !off("tyre_compound", &cur_off) || !off("tyre_defs", &defs_off) ||
        !off("compound_def_size", &def_size) || !off("car_ai_laps", &laps_off))
        return 0;
    ((pfn_this)(g_base + start_game))((void *)c->sim);
    hlog("state=started");
    int alive = 0;
    for (int i = 0; i < g_wait_s * 5; i++) {
        Sleep(200);
        if (read_chain(c) && player_rpm(c) > 1.0f) {
            alive = 1;
            break;
        }
    }
    if (!alive) {
        hlog("player car never came alive");
        return 0;
    }
    void *ai = VirtualAlloc(NULL, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!ai)
        return 0;
    ((pfn_ctor)(g_base + ctor))(ai, (void *)c->car);
    unsigned long long tyre0 = c->car + tyres, vb = 0, ve = 0;
    int cur = *(volatile int *)(tyre0 + cur_off);
    rd64(tyre0 + defs_off, &vb);
    rd64(tyre0 + defs_off + 8, &ve);
    long long count = (ve > vb && def_size) ? (long long)((ve - vb) / def_size) : 0;
    int safe = (count == 0 || (cur >= 0 && cur < count)) ? cur : 0;
    *(volatile int *)((unsigned char *)ai + pref) = safe;
    ((pfn_this)(g_base + init_tyres))(ai);
    ((pfn_set_ctrl)(g_base + set_ctrl))((void *)c->car, ai);
    *(volatile int *)(c->car + laps_off) = 100000;
    hlog("state=ai_driving compound=%d of %lld", safe, count);
    return 1;
}

static int start_race(Chain *c)
{
    unsigned long long fn, stype_off, start_off, clock_off, clock_ms, rm_sim, sim_client,
        holder = 0, sim = 0, client = 1;
    if (!c->rm || !off("start_race", &fn) || !off("rm_session_type", &stype_off) ||
        !off("rm_start_time", &start_off) || !off("rm_clock", &clock_off) ||
        !off("clock_ms", &clock_ms) || !off("rm_sim", &rm_sim) || !off("sim_client", &sim_client))
        return 0;
    int stype = *(volatile int *)(c->rm + stype_off);
    rd64(c->rm + rm_sim, &sim);
    if (sim)
        rd64(sim + sim_client, &client);
    rd64(c->rm + clock_off, &holder);
    if (stype != 3 || client != 0 || !holder) {
        hlog("not starting race: type=%d online=%d clock=%d", stype, client != 0, holder != 0);
        return 0;
    }
    double clock = *(volatile double *)(holder + clock_ms);
    volatile double *start = (volatile double *)(c->rm + start_off);
    if (*start <= clock)
        *start = 1.7976931348623157e308;
    ((pfn_start_race)(g_base + fn))((void *)c->rm, g_start_delay_ms);
    if (*start > 1e300) {
        hlog("race start refused by the game");
        return 0;
    }
    hlog("state=race_started delay_ms=%.0f", g_start_delay_ms);
    return 1;
}

static void render_off(void)
{
    static const unsigned char ret[1] = {0xC3};
    unsigned long long r;
    if (off("game_render", &r))
        patch_bytes(r, ret, 1, "render");
    if (off("game_render_hud", &r))
        patch_bytes(r, ret, 1, "hud render");
    hlog("state=render_off");
}

static DWORD WINAPI session_thread(LPVOID unused)
{
    (void)unused;
    Chain c;
    int ready = 0;
    for (int i = 0; i < g_wait_s * 5; i++) {
        if (read_chain(&c) && player_rpm(&c) >= 0.0f) {
            ready = 1;
            break;
        }
        Sleep(200);
    }
    if (!ready) {
        hlog("state=no_session");
        return 0;
    }
    hlog("state=loaded");
    Sleep(4000);
    read_chain(&c);
    if (g_autodrive && !install_ai(&c)) {
        hlog("state=ai_failed");
        return 0;
    }
    if (g_autostart) {
        read_chain(&c);
        start_race(&c);
    }
    if (g_render_off)
        render_off();
    return 0;
}

#ifdef __GNUC__
static long linux_prctl(long option, long arg)
{
    long ret;
    register long r10 __asm__("r10") = 0;
    register long r8 __asm__("r8") = 0;
    __asm__ volatile("syscall"
                     : "=a"(ret)
                     : "a"(157L), "D"(option), "S"(arg), "d"(0L), "r"(r10), "r"(r8)
                     : "rcx", "r11", "memory");
    return ret;
}
#endif

static void allow_reader(void)
{
    int pid = env_int("ACHL_PTRACER", 0);
    if (pid <= 0)
        return;
    HMODULE nt = GetModuleHandleW(L"ntdll.dll");
    if (!nt || !GetProcAddress(nt, "wine_get_version")) {
        hlog("ACHL_PTRACER ignored, not running under Wine");
        return;
    }
#ifdef __GNUC__
    hlog("memory readable by process %d (result %ld)", pid, linux_prctl(0x59616d61L, pid));
#else
    hlog("ACHL_PTRACER needs a mingw build");
#endif
}

static void init_all(void)
{
    allow_reader();
    g_warp = env_on("ACHL_WARP");
    g_fakeswap = env_on("ACHL_FAKESWAP");
    g_texshrink = env_on("ACHL_TEXSHRINK");
    g_bufshrink = env_on("ACHL_BUFSHRINK");
    g_hidewin = env_on("ACHL_HIDEWIN");
    g_no_audio = env_on("ACHL_NOAUDIO");
    g_no_input = env_on("ACHL_NOINPUT");
    g_sleep0_ms = env_int("ACHL_SLEEP0_MS", 0);
    g_render_off = env_on("ACHL_RENDER_OFF");
    g_autodrive = env_on("ACHL_AUTODRIVE");
    g_autostart = env_on("ACHL_AUTOSTART");
    g_wait_s = env_int("ACHL_WAIT_S", 300);
    g_start_delay_ms = (float)env_int("ACHL_START_DELAY_MS", 3000);
    load_offsets();
    if (g_no_input)
        g_real_di8create =
            (pfn_di8create)iat_patch("dinput8.dll", "DirectInput8Create", (void *)hk_di8create);
    if (g_sleep0_ms > 0)
        g_real_sleep = (pfn_sleep)iat_patch("kernel32.dll", "Sleep", (void *)hk_sleep);
    if (g_no_audio)
        iat_patch("fmodstudio64.dll",
                  "?loadBankFile@System@Studio@FMOD@@QEAA?AW4FMOD_RESULT@@PEBDIPEAPEAVBank@23@@Z",
                  (void *)hk_loadbank);
    if (g_hidewin)
        g_real_cwex = (pfn_cwex)iat_patch("user32.dll", "CreateWindowExW", (void *)hk_cwex);
    g_real_create = (pfn_create)iat_patch("d3d11.dll", "D3D11CreateDevice", (void *)hk_create);
    g_real_create_swap = (pfn_create_swap)iat_patch("d3d11.dll", "D3D11CreateDeviceAndSwapChain",
                                                    (void *)hk_create_swap);
    if (env_on("ACHL_STUBDISPLAYMODE")) {
        static const unsigned char stub[3] = {0xB0, 0x01, 0xC3};
        unsigned long long r;
        if (off("display_mode", &r))
            patch_bytes(r, stub, 3, "display mode query");
    }
    hlog("achl ready warp=%d texshrink=%d bufshrink=%d hidewin=%d noaudio=%d sleep0=%d "
         "render_off=%d autodrive=%d autostart=%d",
         g_warp, g_texshrink, g_bufshrink, g_hidewin, g_no_audio, g_sleep0_ms, g_render_off,
         g_autodrive, g_autostart);
    if (g_render_off || g_autodrive || g_autostart) {
        HANDLE h = CreateThread(NULL, 0, session_thread, NULL, 0, NULL);
        if (h)
            CloseHandle(h);
    }
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason != DLL_PROCESS_ATTACH)
        return TRUE;
    DisableThreadLibraryCalls(inst);
    InitializeCriticalSection(&g_lock);
    g_base = (unsigned char *)GetModuleHandleW(NULL);
    char path[MAX_PATH];
    DWORD n = GetEnvironmentVariableA("ACHL_LOG", path, sizeof(path));
    if (!n || n >= sizeof(path))
        strcpy(path, "achl.log");
    g_log = fopen(path, "w");
    n = GetEnvironmentVariableW(L"ACHL_DOCS", g_docs, MAX_PATH);
    if (n > 0 && n < MAX_PATH) {
        g_real_shgfp = (pfn_shgfp)iat_patch("shell32.dll", "SHGetFolderPathW", (void *)hk_shgfp);
        hlog("documents folder: %S", g_docs);
    } else {
        g_docs[0] = 0;
    }
    init_all();
    return TRUE;
}
