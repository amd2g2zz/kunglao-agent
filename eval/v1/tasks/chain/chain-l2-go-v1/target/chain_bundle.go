// CONSTRUCTED eval target (family chain-go, gradient L2, tier chain).
// NOT malware; no real workspace data: a seeded synthetic fixture
// minted by scripts/eval_chain.py (issue #370).
// [layer 1 - custom packer: magic envelope + XOR key stream over
//  the field blob; peel = decode + unXOR with the seeded key]
package main

import (
	"bufio"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
)

var PACKED = []string{
	"43463730504b31a42f869fbe6555e3e9760fbe3a949ef5e66f80cebb7158f5ea2154e83a96c4f5e6",
	"710ceb3d9095aee93c81cfeb754dedf97108ee30de85f7fd3f869bea225cf8e32c0fe868c591faeb",
	"7109ec67c3c5a8b93ed59ded730ea5b8770fe83c92c4faec3d84caee7309f8ef2d08bc3ac292fbe9",
	"39d0a4f56507aeb57014fd30d385f7fd6c80c8eb7159a7b97155bc6f9293aebb39d5cfba710ea4ec",
	"3c83c9e0705ef5ed710ebb3d9fc3feb935dc9beb7757f0e2760fb569c195fdba6bdc9cee235da0ed",
	"700bb43a90c3ffbe3b86c8bb735df8bf235cbc67c4c5faec38d29ae8765fa7be745dee6b94c2afed",
	"275fee669496fbe634809de07f56a3be735ebd3b9393acbb6e879bbc245aa2ec2659ec3c9092abec",
	"7154af7385c1bdfd37becae1775ff7e22d55b86c8b94faee38d0c1ea7559f8f7275bb56e9397fdea",
	"39849ce02257f4eb2355b83c9fc2acbe3887c1ef250df9b8705bba6c9593fbba6f83c1bb2258a4ea",
	"3d8198ed7f09a3ed2508e96b9294f5ba3ddc9fb87759f3e22659ef6cc694fee93fdc9fea775ea0ef",
	"765cb56bc29efae968d4ccba2558f3ee770eb46f9ec1fdba3cdccceb220ea0eb200ceb67c3c5f8ef",
	"3981c9ec7357a4eb2d0bbb6f9195f4ec3987cab8745cf7e92c0bbe6f96c6fbed38869cea7159f0e2",
	"2408e867949efbbb6ed49fbf765ca2bd205fbe3cc69eafbd3ed2c0e9230ef7ea2655bb66c59fabea",
	"2fc9dbaa2603b5f92f5fbc669f93f5e93fd1c8a4",
	"3cd1c0bc225ea2e32c5ceb6f9e90fceb3b819aef2509a5e8735cb43995c5f5ee34879bbd715ef3eb",
	"35d09ae1220ea0ee7755bb3dc59fabba3ed2caeb7359a4ba200eb53d94c5f9bb3a81c8ba255da7ed",
}

var PACK_KEY = []byte{223, 13, 229, 249, 217, 71, 111, 193, 219, 21, 109, 141, 95, 167, 167, 205}

// junk wedges (opaque predicates, package level): the naive
// read of this source misleads until stripped
var _opq_j1baea = uint32((0xcc0b86c9 ^ 0x70f8ecb5) >> 3)
var _opq_j1baeb = _opq_j1baea ^ uint32(0xecb5)
var _opq_j1baec = _opq_j1baeb & 0xf // opaque: reads data-dependent
var RC = [8][4]uint32{
	{uint32(15933481), uint32(1335373717), uint32(2832334809), uint32(3135368931)},
	{uint32(999144899), uint32(966359789), uint32(815563041), uint32(537120847)},
	{uint32(3565433415), uint32(606050849), uint32(3557578547), uint32(2695889195)},
	{uint32(2094929639), uint32(2469423191), uint32(2873667403), uint32(1353733097)},
	{uint32(3411617021), uint32(4028066701), uint32(1828928997), uint32(3882689179)},
	{uint32(2352053759), uint32(1702425069), uint32(971608447), uint32(3506951055)},
	{uint32(369844169), uint32(3547699879), uint32(4117690263), uint32(3184056061)},
	{uint32(339293075), uint32(882543493), uint32(982956839), uint32(2354767205)},
}

type coreParams struct {
	C0   uint32 `json:"c0"`
	C1   uint32 `json:"c1"`
	C2   uint32 `json:"c2"`
	Rot  uint32 `json:"rot"`
	Odd  uint32 `json:"odd"`
	Odd2 uint32 `json:"odd2"`
}

func rotl(x uint32, r int) uint32 {
	r &= 31
	if r == 0 {
		return x
	}
	return (x << uint(r)) | (x >> uint(32-r))
}

func arx(w [4]uint32, rc [4]uint32) [4]uint32 {
	a, b, c, d := w[0], w[1], w[2], w[3]
	a = a + d
	b ^= rotl(a, int(rc[0]&15)+1)
	c = c + b
	d ^= rotl(c, int(rc[1]&15)+1)
	a = a + b
	c ^= rotl(a, int(rc[2]&15)+1)
	d = d + c
	b ^= rotl(d, int(rc[3]&15)+1)
	return [4]uint32{a, b, c, d}
}

func kdfWords(fp [3]uint32, salt uint32) [4]uint32 {
	w := [4]uint32{(fp[0] ^ RC[0][0]) | 1, fp[1] ^ RC[0][1],
		fp[2] ^ RC[0][2], salt ^ RC[0][3]}
	for r := 0; r < 8; r++ {
		w = arx(w, RC[r%8])
		w[r%4] ^= uint32(r+1) * uint32(0x2545F491)
	}
	return w
}

func blk(keyW [4]uint32, ctr uint32) [4]uint32 {
	w := [4]uint32{keyW[0], keyW[1], keyW[2], keyW[3] ^ ctr}
	for r := 0; r < 6; r++ {
		w = arx(w, RC[(r+2)%8])
	}
	return w
}

func decryptHex(hexStr string, fp [3]uint32, salt uint32) []byte {
	raw, err := hex.DecodeString(hexStr)
	if err != nil {
		panic(err)
	}
	keyW := kdfWords(fp, salt)
	out := make([]byte, 0, len(raw))
	for ctr, off := 0, 0; off < len(raw); ctr, off = ctr+1, off+16 {
		ks := blk(keyW, uint32(ctr))
		end := off + 16
		if end > len(raw) {
			end = len(raw)
		}
		for j, b := range raw[off:end] {
			out = append(out, b^byte(ks[j/4]>>uint((3-j%4)*8)))
		}
	}
	return out
}

func cfgOf(hexStr string, fp [3]uint32, salt uint32) map[string]json.RawMessage {
	plain := decryptHex(hexStr, fp, salt)
	if len(plain) < 4 || string(plain[:4]) != "CF70" {
		panic("config magic mismatch")
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(plain[4:], &m); err != nil {
		panic(err)
	}
	return m
}

func core(p coreParams, data []byte, lane int) string {
	c0, c1 := p.C0, p.C1
	if lane != 0 {
		c0 ^= rotl(p.Odd*uint32(lane), 3)
		c1 = c1 + p.Odd2*uint32(lane)
	}
	a, b, acc := c0, c1, p.C2
	for _, by := range data {
		a = a + uint32(by)
		a = rotl(a^b, int(p.Rot))
		b = b + a
		acc = acc ^ rotl(a+acc, 3)
	}
	h1 := acc * p.Odd
	h2 := rotl(h1^b, 7) * p.Odd
	return fmt.Sprintf("%08x%08x", h1, h2)
}

func mac(keyHex string, data []byte) string {
	var w [4]uint32
	for i := 0; i < 4; i++ {
		v, _ := strconv.ParseUint(keyHex[i*8:(i+1)*8], 16, 32)
		w[i] = uint32(v)
	}
	padded := append(append([]byte{}, data...), 0x80)
	for len(padded)%4 != 0 {
		padded = append(padded, 0)
	}
	for off, k := 0, 0; off < len(padded); off, k = off+4, k+1 {
		w[0] ^= uint32(padded[off])<<24 | uint32(padded[off+1])<<16 |
			uint32(padded[off+2])<<8 | uint32(padded[off+3])
		w = arx(w, RC[k%8])
	}
	w = arx(w, RC[0])
	w = arx(w, RC[1])
	return fmt.Sprintf("%08x%08x", w[0]^w[2], w[1]^w[3])
}

func paramsOf(m map[string]json.RawMessage, key string) coreParams {
	var p coreParams
	if err := json.Unmarshal(m[key], &p); err != nil {
		panic(err)
	}
	return p
}

var LEGACY_SEL = uint32(0x5c)

var _w_j1bae_scratch uint32

func unpackBlob() blobDoc {
	total := ""
	for _, i := range PACK_ORDER {
		total += PACKED[i]
	}
	raw, err := hex.DecodeString(total)
	if err != nil {
		panic(err)
	}
	if len(raw) < 7 || string(raw[:7]) != "CF70PK1" {
		panic("packer magic mismatch")
	}
	out := make([]byte, len(raw)-7)
	for i, b := range raw[7:] {
		out[i] = b ^ PACK_KEY[i%len(PACK_KEY)]
	}
	var doc blobDoc
	if err := json.Unmarshal(out, &doc); err != nil {
		panic(err)
	}
	return doc
}

type blobDoc struct {
	Cfg      string   `json:"cfg"`
	Decoy    string   `json:"decoy"`
	Fp       []uint32 `json:"fp"`
	Honeypot string   `json:"honeypot"`
	Salt     uint32   `json:"salt"`
}

var PACK_ORDER = []int{
	0, 4, 10, 11, 2, 15, 1, 14, 5, 9, 6, 8, 7, 3, 12, 13,
}

func derive(payloadHex string, lane int) string {
	doc := unpackBlob()
	var fp [3]uint32
	copy(fp[:], doc.Fp)
	legacySel := (fp[2] ^ doc.Salt) & 0xff
	data, err := hex.DecodeString(payloadHex)
	if err != nil {
		panic(err)
	}
	_w_j1bae_scratch = legacySel // junk scratch (discarded)
	trueCfg := cfgOf(doc.Cfg, fp, doc.Salt)
	if legacySel == LEGACY_SEL {
		legacyCfg := cfgOf(doc.Decoy, fp, doc.Salt)
		return core(paramsOf(legacyCfg, "core"), data, 0)
	}
	return core(paramsOf(trueCfg, "core"), data, lane)
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var row struct {
			I       int    `json:"i"`
			Payload string `json:"payload"`
			Lane    int    `json:"lane"`
		}
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			panic(err)
		}
		fmt.Fprintf(out, "{\"i\": %d, \"out\": %q}\n",
			row.I, derive(row.Payload, row.Lane))
	}
}
