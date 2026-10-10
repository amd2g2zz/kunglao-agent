/* apk-webview-attest-v2 — native layer. The compare constant is DERIVED
 * from the JS-issued seed: claimed must equal sha256(seed||nonce)[:8]
 * XOR MASK. Neither layer alone accepts: JS cannot mint claimed without
 * MASK (native-only); native cannot run without a seed (JS-challenge-only).
 * libc-free (unicorn-runnable). */
#include <stdint.h>

static const uint8_t MASK[8] = {0xc4, 0x2b, 0x91, 0x6f, 0x18, 0xd3, 0x7a, 0x05};

static const uint32_t K[64] = {
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
#define RR(v,n) (((v)>>(n))|((v)<<(32-(n))))
static void sha256(const uint8_t *m, int len, uint8_t out[32]) {
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    uint8_t buf[128];
    for (int i = 0; i < 128; i++) buf[i] = 0;
    for (int i = 0; i < (len < 128 ? len : 128); i++) buf[i] = m[i];
    buf[len < 128 ? len : 127] = 0x80;
    uint64_t bl = (uint64_t)len * 8;
    int nb = (len < 56) ? 1 : 2;
    int lp = (len < 56) ? 56 : 120;
    for (int i = 0; i < 8; i++) buf[lp + i] = (uint8_t)((bl >> (56 - 8 * i)) & 0xff);
    for (int j = 0; j < nb * 64; j += 64) {
        uint32_t w[64];
        for (int i = 0; i < 16; i++) w[i]=(buf[j+i*4]<<24)|(buf[j+i*4+1]<<16)|(buf[j+i*4+2]<<8)|buf[j+i*4+3];
        for (int i = 16; i < 64; i++){uint32_t s0=RR(w[i-15],7)^RR(w[i-15],18)^(w[i-15]>>3),s1=RR(w[i-2],17)^RR(w[i-2],19)^(w[i-2]>>10);w[i]=w[i-16]+s0+w[i-7]+s1;}
        uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
        for (int i=0;i<64;i++){uint32_t S1=RR(e,6)^RR(e,11)^RR(e,25),ch=(e&f)^(~e&g),t1=hh+S1+ch+K[i]+w[i],S0=RR(a,2)^RR(a,13)^RR(a,22),mj=(a&b)^(a&c)^(b&c),t2=S0+mj;hh=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;}
        h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=hh;
    }
    for (int i=0;i<8;i++){out[i*4]=h[i]>>24;out[i*4+1]=h[i]>>16;out[i*4+2]=h[i]>>8;out[i*4+3]=h[i];}
}

/* seed: 16 bytes from the JS layer; nonce: the JS PoW nonce (ascii);
 * claimed: 8 bytes the caller presents. */
int32_t attest_verify(const uint8_t *seed, int32_t seed_len,
                      const uint8_t *nonce, int32_t nonce_len,
                      const uint8_t *claimed, int32_t claimed_len) {
    if (!seed || seed_len != 16 || !nonce || nonce_len < 1 ||
        !claimed || claimed_len != 8) return 1;
    uint8_t buf[64];
    int i;
    for (i = 0; i < 16; i++) buf[i] = seed[i];
    int use = nonce_len < 48 ? nonce_len : 48;
    for (i = 0; i < use; i++) buf[16 + i] = nonce[i];
    uint8_t d[32];
    sha256(buf, 16 + use, d);
    for (i = 0; i < 8; i++)
        if ((uint8_t)(d[i] ^ MASK[i]) != claimed[i]) return 1;
    return 0;
}
