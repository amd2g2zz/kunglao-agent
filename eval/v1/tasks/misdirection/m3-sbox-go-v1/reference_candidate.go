// reference candidate: the true derivation (self-check).
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

const (
	k0      uint32 = 0xb5c2b38f
	z       uint32 = 0xe921c93b
	rotBase uint32 = 0x8d8537f5
)

func rotl32(x uint32, r uint) uint32 {
	return (x << r) | (x >> (32 - r))
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
		t := (uint32(req.I) + 1) * rotBase
		out := ((req.In + rotl32(t, (uint(req.I)%31)+1) + z) & 0xffffffff) ^ k0
		fmt.Fprintf(w, "{\"i\": %d, \"in\": %d, \"out\": %d}\n",
			req.I, req.In, out)
	}
}
