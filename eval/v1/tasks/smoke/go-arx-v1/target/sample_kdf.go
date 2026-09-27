// sample_kdf.go — CONSTRUCTED eval target (family go-arx, eval-v1).
// NOT malware; no real workspace data: every constant below is a seeded
// mutation of the SHA-1-family mechanism shape, minted by eval_targets.py.
//
// Recover the three embedded constants and re-implement the pipeline:
//   out = ((in + rotl32((i+1)*rotBase, (i%31)+1) + z) mod 2^32) XOR k0
// The published capture pins the fixed face
//   params[i] = uint32(i)*2654435761 + 1
// but the program is INPUT-AGNOSTIC: it reads one JSON object per line on
// stdin ({"i": N, "in": X}) and prints one per line
// ({"i": N, "in": X, "out": Y}) — the checker drives freshly minted
// inputs through it, so a PASS requires the actual derivation (a
// constants+lookup shortcut fails on inputs it never saw).
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

const (
	k0      uint32 = 0x0922f7b7
	z       uint32 = 0x7d2c637f
	rotBase uint32 = 0x9c3dde83
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
