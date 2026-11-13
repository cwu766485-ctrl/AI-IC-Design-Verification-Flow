module tb_fifo;
  logic clk = 0;
  logic rst_n = 0;
  logic push = 0;
  logic pop = 0;
  logic [7:0] data_in = 0;
  logic [7:0] data_out;
  fifo dut(.*);
  always #5 clk = ~clk;
  initial begin
    @(posedge clk); rst_n <= 1;
    @(posedge clk); push <= 1; data_in <= 8'hA5;
    @(posedge clk); push <= 0;
    @(posedge clk);
    if (data_out !== 8'hA5) $fatal(1, "FIFO data mismatch");
    $display("TEST PASSED");
    $finish;
  end
endmodule
