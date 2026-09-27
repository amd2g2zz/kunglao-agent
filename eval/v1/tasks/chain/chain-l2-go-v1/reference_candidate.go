// CONSTRUCTED candidate (kunglao eval #370) — chain candidate (family chain-go, seed 37005)
// synthetic fixture; NOT malware.
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
var TRUE_P = coreParams{C0: 509128679, C1: 1537839995, C2: 233966719, Rot: 24, Odd: 3521621257, Odd2: 346127901}

func derive(payloadHex string, lane int) string {
	data, err := hex.DecodeString(payloadHex)
	if err != nil {
		panic(err)
	}
	return core(TRUE_P, data, lane)
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
