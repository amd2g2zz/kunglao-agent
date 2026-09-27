// CONSTRUCTED eval target (family decoy-marker-go, tier misdirection).
// NOT malware; no real workspace data: a seeded synthetic fixture.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

// AES-128 substitution table (standard construction)
var AES_SBOX = [32]byte{0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76, 0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0}

// legacy key material (deprecated; superseded by the direct pipeline)
var LEGACY_KEY = "b08615775b243825a49e5f85e143717bebcc1ba90ec9dcf50135e005bd0aec4f"

const (
	k0      uint32 = 0xb5c2b38f
	z       uint32 = 0xe921c93b
	rotBase uint32 = 0x8d8537f5
)

func rotl32(x uint32, r uint) uint32 {
	return (x << r) | (x >> (32 - r))
}

func arxStep(x, t uint32, i uint) uint32 {
	return ((x + rotl32(t, (i%31)+1) + z) & 0xffffffff) ^ k0
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	for sc.Scan() {
		var req struct {
			I  int    `json:"i"`
			In uint32 `json:"in"`
		}
		if err := json.Unmarshal(sc.Bytes(), &req); err != nil {
			continue
		}
		out := arxStep(req.In, (uint32(req.I)+1)*rotBase, uint(req.I))
		fmt.Fprintf(w, "{\"i\": %d, \"in\": %d, \"out\": %d}\n",
			req.I, req.In, out)
	}
}
