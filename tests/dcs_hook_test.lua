-- DCS hook test with a mocked DCS + LuaSocket (DCS's own luae.exe):  luae tests\dcs_hook_test.lua <hook path>
local hook = arg[1]
local fails = 0
local function check(c, what) if not c then fails = fails + 1; print('FAIL ' .. what) end end

local inbox, outbox, sent = {}, {}, {}
package.preload['socket'] = function()
    return { udp = function()
        local s = {}
        function s:settimeout() end
        function s:setsockname() return true end
        function s:setpeername() return true end
        function s:receive() return table.remove(inbox, 1) end
        function s:send(m) outbox[#outbox + 1] = m; return true end
        function s:close() end
        return s
    end }
end
local now, unit, cb = 100.0, 'CH-47Fbl1', nil
log = { INFO = 1, write = function() end }
DCS = { setUserCallbacks = function(c) cb = c end, getRealTime = function() return now end,
        getPlayerUnitType = function() return unit end }
Export = { LoSetCommand = function(id, v) sent[#sent + 1] = { id, v } end }

dofile(hook)
check(cb ~= nil, 'callbacks registered')
cb.onSimulationStart()

-- active packet -> six commands with the right ids and clamped values
inbox[#inbox + 1] = 'HTK1 1 1 0.1 -0.2 0.3 0.4 -0.5 1.7'
cb.onSimulationFrame()
check(#sent == 6, 'six commands (' .. #sent .. ')')
check(sent[1][1] == 2010 and math.abs(sent[1][2] - 0.1) < 1e-9, 'yaw id 2010')
check(sent[2][1] == 2011 and sent[3][1] == 2047 and sent[4][1] == 2049 and sent[5][1] == 2051 and sent[6][1] == 2053, 'ids in order')
check(sent[6][2] == 1, 'clamped to 1')

-- only the newest of several packets is applied
sent = {}
inbox[#inbox + 1] = 'HTK1 2 1 0.0 0 0 0 0 0'
inbox[#inbox + 1] = 'HTK1 3 1 0.9 0 0 0 0 0'
now = now + 0.01
cb.onSimulationFrame()
check(#sent == 6 and math.abs(sent[1][2] - 0.9) < 1e-9, 'newest packet applied')

-- paused -> nothing (mouse look free)
sent = {}
inbox[#inbox + 1] = 'HTK1 4 0 0.5 0 0 0 0 0'
now = now + 0.01
cb.onSimulationFrame()
check(#sent == 0, 'paused sends nothing')

-- active again, then the app goes quiet: stale after 0.3 s -> nothing
inbox[#inbox + 1] = 'HTK1 5 1 0.2 0 0 0 0 0'
now = now + 0.01
cb.onSimulationFrame()
sent = {}
now = now + 0.5
cb.onSimulationFrame()
check(#sent == 0, 'stale sends nothing')

-- garbage is ignored, no error
inbox[#inbox + 1] = 'hello'
now = now + 0.01
local ok = pcall(cb.onSimulationFrame)
check(ok, 'bad packet does not raise')

-- status line back to the app
now = now + 2
cb.onSimulationFrame()
local st = outbox[#outbox] or ''
check(st:match('^HTKS 1%.0%.0 CH%-47Fbl1 %d %d+$') ~= nil, 'status line (' .. st .. ')')

print(fails == 0 and 'all checks passed' or (fails .. ' check(s) failed'))
os.exit(fails == 0 and 0 or 1)
