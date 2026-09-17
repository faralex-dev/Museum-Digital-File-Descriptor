/*
 * Хеш-функция «Стрибог» (ГОСТ 34.11-2018, он же ГОСТ Р 34.11-2012), 256 и 512 бит.
 *
 * Модуль расширения Python. Интерфейс повторяет объекты hashlib:
 *     h = _streebog.new(256); h.update(data); h.hexdigest()
 *
 * Порядок байтов совпадает с pystribog, gostcrypto и OpenSSL gost-engine:
 * для сообщения "012345678901234567890123456789012345678901234567890123456789012"
 * результат 256 бит — 9d151eefd8590b89daa6ba6cb74af9275dd051026bb149a452fd84e5e57b5500.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>

#include "_streebog_tables.h"

#define BLOCK 64
/* Порог, после которого update() отпускает GIL. */
#define GIL_RELEASE_MIN 4096

static inline uint64_t load64(const unsigned char *p)
{
    return (uint64_t)p[0] | ((uint64_t)p[1] << 8) | ((uint64_t)p[2] << 16) |
           ((uint64_t)p[3] << 24) | ((uint64_t)p[4] << 32) | ((uint64_t)p[5] << 40) |
           ((uint64_t)p[6] << 48) | ((uint64_t)p[7] << 56);
}

static inline void store64(unsigned char *p, uint64_t v)
{
    for (int i = 0; i < 8; i++) {
        p[i] = (unsigned char)(v >> (8 * i));
    }
}

/* Преобразование LPS через предвычисленные таблицы. x и y не должны совпадать. */
static inline void lps(const uint64_t *x, uint64_t *y)
{
    for (int i = 0; i < 8; i++) {
        int s = 8 * i;
        y[i] = STREEBOG_T[0][(x[0] >> s) & 0xff] ^ STREEBOG_T[1][(x[1] >> s) & 0xff] ^
               STREEBOG_T[2][(x[2] >> s) & 0xff] ^ STREEBOG_T[3][(x[3] >> s) & 0xff] ^
               STREEBOG_T[4][(x[4] >> s) & 0xff] ^ STREEBOG_T[5][(x[5] >> s) & 0xff] ^
               STREEBOG_T[6][(x[6] >> s) & 0xff] ^ STREEBOG_T[7][(x[7] >> s) & 0xff];
    }
}

/* Функция сжатия g_N(h, m). */
static void compress(uint64_t *h, const uint64_t *n, const uint64_t *m)
{
    uint64_t k[8], state[8], tmp[8];
    int i, r;

    for (i = 0; i < 8; i++) tmp[i] = h[i] ^ n[i];
    lps(tmp, k);
    for (i = 0; i < 8; i++) state[i] = k[i] ^ m[i];

    for (r = 0; r < 12; r++) {
        lps(state, tmp);
        for (i = 0; i < 8; i++) state[i] = k[i] ^ STREEBOG_C[r][i];
        lps(state, k);
        for (i = 0; i < 8; i++) state[i] = tmp[i] ^ k[i];
    }
    for (i = 0; i < 8; i++) h[i] ^= state[i] ^ m[i];
}

/* a = a + b (mod 2^512) */
static void add512(uint64_t *a, const uint64_t *b)
{
    uint64_t carry = 0;
    for (int i = 0; i < 8; i++) {
        uint64_t s = a[i] + b[i];
        uint64_t c1 = s < a[i];
        uint64_t s2 = s + carry;
        uint64_t c2 = s2 < s;
        a[i] = s2;
        carry = c1 | c2;
    }
}

static void add_small(uint64_t *a, uint64_t v)
{
    uint64_t b[8] = {v, 0, 0, 0, 0, 0, 0, 0};
    add512(a, b);
}

typedef struct {
    uint64_t h[8];
    uint64_t n[8];
    uint64_t sigma[8];
    unsigned char buf[BLOCK];
    size_t buflen;
    int bits;
} streebog_ctx;

static void ctx_init(streebog_ctx *c, int bits)
{
    memset(c, 0, sizeof(*c));
    c->bits = bits;
    if (bits == 256) {
        for (int i = 0; i < 8; i++) c->h[i] = 0x0101010101010101ULL;
    }
}

static void process_block(streebog_ctx *c, const unsigned char *p)
{
    uint64_t m[8];
    for (int i = 0; i < 8; i++) m[i] = load64(p + 8 * i);
    compress(c->h, c->n, m);
    add_small(c->n, 512);
    add512(c->sigma, m);
}

static void ctx_update(streebog_ctx *c, const unsigned char *data, size_t len)
{
    if (c->buflen) {
        size_t take = BLOCK - c->buflen;
        if (take > len) take = len;
        memcpy(c->buf + c->buflen, data, take);
        c->buflen += take;
        data += take;
        len -= take;
        if (c->buflen == BLOCK) {
            process_block(c, c->buf);
            c->buflen = 0;
        }
    }
    while (len >= BLOCK) {
        process_block(c, data);
        data += BLOCK;
        len -= BLOCK;
    }
    if (len) {
        memcpy(c->buf, data, len);
        c->buflen = len;
    }
}

static void ctx_final(const streebog_ctx *src, unsigned char *out)
{
    streebog_ctx c = *src;
    unsigned char block[BLOCK];
    uint64_t m[8];
    static const uint64_t zero[8] = {0};

    memset(block, 0, BLOCK);
    memcpy(block, c.buf, c.buflen);
    block[c.buflen] = 0x01;
    for (int i = 0; i < 8; i++) m[i] = load64(block + 8 * i);

    compress(c.h, c.n, m);
    add_small(c.n, (uint64_t)c.buflen * 8);
    add512(c.sigma, m);
    compress(c.h, zero, c.n);
    compress(c.h, zero, c.sigma);

    unsigned char full[BLOCK];
    for (int i = 0; i < 8; i++) store64(full + 8 * i, c.h[i]);
    if (c.bits == 256) {
        memcpy(out, full + 32, 32);
    } else {
        memcpy(out, full, 64);
    }
}

/* ---------------- Python-объект ---------------- */

typedef struct {
    PyObject_HEAD
    streebog_ctx ctx;
} StreebogObject;

static PyTypeObject StreebogType;

static PyObject *
streebog_update(StreebogObject *self, PyObject *arg)
{
    Py_buffer view;
    if (PyObject_GetBuffer(arg, &view, PyBUF_SIMPLE) < 0) {
        return NULL;
    }
    if (view.len >= GIL_RELEASE_MIN) {
        Py_BEGIN_ALLOW_THREADS
        ctx_update(&self->ctx, (const unsigned char *)view.buf, (size_t)view.len);
        Py_END_ALLOW_THREADS
    } else {
        ctx_update(&self->ctx, (const unsigned char *)view.buf, (size_t)view.len);
    }
    PyBuffer_Release(&view);
    Py_RETURN_NONE;
}

static PyObject *
streebog_digest(StreebogObject *self, PyObject *Py_UNUSED(ignored))
{
    unsigned char out[64];
    ctx_final(&self->ctx, out);
    return PyBytes_FromStringAndSize((const char *)out, self->ctx.bits / 8);
}

static PyObject *
streebog_hexdigest(StreebogObject *self, PyObject *Py_UNUSED(ignored))
{
    static const char hex[] = "0123456789abcdef";
    unsigned char out[64];
    char text[128];
    int n = self->ctx.bits / 8;
    ctx_final(&self->ctx, out);
    for (int i = 0; i < n; i++) {
        text[2 * i] = hex[out[i] >> 4];
        text[2 * i + 1] = hex[out[i] & 0x0f];
    }
    return PyUnicode_FromStringAndSize(text, 2 * n);
}

static PyObject *
streebog_copy(StreebogObject *self, PyObject *Py_UNUSED(ignored))
{
    StreebogObject *other = PyObject_New(StreebogObject, &StreebogType);
    if (other == NULL) {
        return NULL;
    }
    other->ctx = self->ctx;
    return (PyObject *)other;
}

static PyObject *
streebog_get_digest_size(StreebogObject *self, void *Py_UNUSED(closure))
{
    return PyLong_FromLong(self->ctx.bits / 8);
}

static PyObject *
streebog_get_block_size(StreebogObject *Py_UNUSED(self), void *Py_UNUSED(closure))
{
    return PyLong_FromLong(BLOCK);
}

static PyObject *
streebog_get_name(StreebogObject *self, void *Py_UNUSED(closure))
{
    return PyUnicode_FromString(self->ctx.bits == 256 ? "streebog256" : "streebog512");
}

static PyMethodDef streebog_methods[] = {
    {"update", (PyCFunction)streebog_update, METH_O, "Добавить данные."},
    {"digest", (PyCFunction)streebog_digest, METH_NOARGS, "Значение хеша (bytes)."},
    {"hexdigest", (PyCFunction)streebog_hexdigest, METH_NOARGS, "Значение хеша (hex)."},
    {"copy", (PyCFunction)streebog_copy, METH_NOARGS, "Копия состояния."},
    {NULL, NULL, 0, NULL}
};

static PyGetSetDef streebog_getset[] = {
    {"digest_size", (getter)streebog_get_digest_size, NULL, NULL, NULL},
    {"block_size", (getter)streebog_get_block_size, NULL, NULL, NULL},
    {"name", (getter)streebog_get_name, NULL, NULL, NULL},
    {NULL, NULL, NULL, NULL, NULL}
};

static PyTypeObject StreebogType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "mdfd.hashing._streebog.Streebog",
    .tp_basicsize = sizeof(StreebogObject),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Хеш «Стрибог» (ГОСТ 34.11-2018).",
    .tp_methods = streebog_methods,
    .tp_getset = streebog_getset,
};

static PyObject *
module_new(PyObject *Py_UNUSED(module), PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {"bits", "data", NULL};
    int bits = 256;
    PyObject *data = NULL;
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|iO", kwlist, &bits, &data)) {
        return NULL;
    }
    if (bits != 256 && bits != 512) {
        PyErr_SetString(PyExc_ValueError, "bits должен быть 256 или 512");
        return NULL;
    }
    StreebogObject *self = PyObject_New(StreebogObject, &StreebogType);
    if (self == NULL) {
        return NULL;
    }
    ctx_init(&self->ctx, bits);
    if (data != NULL) {
        PyObject *r = streebog_update(self, data);
        if (r == NULL) {
            Py_DECREF(self);
            return NULL;
        }
        Py_DECREF(r);
    }
    return (PyObject *)self;
}

static PyMethodDef module_methods[] = {
    {"new", (PyCFunction)(void (*)(void))module_new, METH_VARARGS | METH_KEYWORDS,
     "new(bits=256, data=None) -> объект хеша «Стрибог»."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef streebog_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_streebog",
    .m_doc = "Хеш «Стрибог» (ГОСТ 34.11-2018), реализация на C.",
    .m_size = -1,
    .m_methods = module_methods,
};

PyMODINIT_FUNC
PyInit__streebog(void)
{
    if (PyType_Ready(&StreebogType) < 0) {
        return NULL;
    }
    return PyModule_Create(&streebog_module);
}
