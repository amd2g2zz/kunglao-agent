/* apk-static-license-v1 — single-constant license check.
 * accept iff sha256(input)[:8] XOR MASK8 == EXPECT8, input >= 16 bytes.
 * no decoys, no lanes, no anti-debug: the v1 baseline. */
#include <stdint.h>

static const uint8_t EXPECT[8] = {0x88, 0x43, 0x4c, 0x54, 0x35, 0xe0, 0x1e, 0x14};

/* compact sha256 (public-domain style) */
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
static void sha256(const uint8_t *msg, size_t len, uint8_t out[32]) {
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    uint8_t buf[128]; size_t total=len;
    for (int i = 0; i < 128; i++) buf[i] = 0;
    for (size_t i = 0; i < (len < 128 ? len : 128); i++) buf[i] = msg[i]; /* v1: capped */
    buf[len<128?len:127]=0x80;
    uint64_t bl=(uint64_t)total*8;
    size_t nblocks = (len < 56) ? 1 : 2;
    size_t lenpos = (len < 56) ? 56 : 120;   /* block bytes 56..63 of the final block */
    for(int i=0;i<8;i++) buf[lenpos+i]=(uint8_t)((bl>>(56-8*i))&0xff); /* big-endian */
    for(size_t j=0;j<nblocks*64;j+=64){
        uint32_t w[64];
        for(int i=0;i<16;i++) w[i]=(buf[j+i*4]<<24)|(buf[j+i*4+1]<<16)|(buf[j+i*4+2]<<8)|buf[j+i*4+3];
        for(int i=16;i<64;i++){uint32_t s0=RR(w[i-15],7)^RR(w[i-15],18)^(w[i-15]>>3),s1=RR(w[i-2],17)^RR(w[i-2],19)^(w[i-2]>>10);w[i]=w[i-16]+s0+w[i-7]+s1;}
        uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
        for(int i=0;i<64;i++){uint32_t S1=RR(e,6)^RR(e,11)^RR(e,25),ch=(e&f)^(~e&g),t1=hh+S1+ch+K[i]+w[i],S0=RR(a,2)^RR(a,13)^RR(a,22),mj=(a&b)^(a&c)^(b&c),t2=S0+mj;hh=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;}
        h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=hh;
    }
    for(int i=0;i<8;i++){out[i*4]=h[i]>>24;out[i*4+1]=h[i]>>16;out[i*4+2]=h[i]>>8;out[i*4+3]=h[i];}
}

int32_t license_verify(const uint8_t *data, int32_t len) {
    if (data == 0 || len < 16) return 1;          /* reject: too short */
    if (len > 127) return 2;                      /* reject: over cap */
    uint8_t d[32];
    sha256(data, (size_t)len, d);
    for (int i = 0; i < 8; i++)
        if ((uint8_t)(d[i] ^ 0xA5) != EXPECT[i]) return 1;  /* reject */
    return 0;                                      /* accept */
}

int32_t license_probe(const uint8_t *data, int32_t len) {
    /* observability face: first 4 bytes of the digest as int32 (BE) */
    if (data == 0 || len < 0) return -1;
    uint8_t d[32];
    sha256(data, (size_t)(len > 127 ? 127 : len), d);
    return (int32_t)(((uint32_t)d[0] << 24) | ((uint32_t)d[1] << 16) |
                     ((uint32_t)d[2] << 8) | (uint32_t)d[3]);
}
